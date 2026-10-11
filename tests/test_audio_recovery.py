"""Recovery must preserve a usable mic through failed and interrupted updates."""
import threading
import time

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QPushButton

from soundboard import directmic as dm
from soundboard.settings import SettingsDialog
from soundboard.ui.audiorecovery import RecoveryCard
from test_mainwindow import window  # noqa: F401


def wait(qapp, condition):
    end = time.monotonic() + 5
    while not condition() and time.monotonic() < end:
        qapp.processEvents()
        time.sleep(.005)
    assert condition()


@pytest.mark.parametrize('action', ['repair', 'reinstall', 'remove'])
def test_confirmation_cancel_changes_nothing(window, monkeypatch, action):  # noqa: F811
    asked = []
    monkeypatch.setattr(dm, '_elevated', lambda *a: asked.append(a))
    d = SettingsDialog(window, 'audio')
    card = d.findChild(RecoveryCard)
    card.confirm(action)
    card.confirm(action)  # repeated clicks keep the same confirmation
    assert card.dialog.isVisible()
    next(b for b in card.dialog.findChildren(QPushButton) if b.text() == 'Cancel').click()
    assert not asked and not card.recovery.running
    d.close()


@pytest.mark.parametrize('action,clean', [('repair', False), ('reinstall', True)])
def test_recovery_finishes_after_settings_is_deleted(window, qapp, monkeypatch, action, clean):  # noqa: F811
    gate, entered = threading.Event(), threading.Event()
    calls, refreshed = [], []
    window.cfg.mic_device = 'Test mic'
    monkeypatch.setattr(window, '_when_devices_free', lambda fn: refreshed.append(fn))
    monkeypatch.setattr(dm, 'status', lambda mic=None: 'ready')

    def install(mic, *, clean=False):
        calls.append((mic, clean))
        entered.set()
        assert gate.wait(5)
    monkeypatch.setattr(dm, 'install', install)
    d = SettingsDialog(window, 'audio')
    card = d.findChild(RecoveryCard)
    controller = card.recovery
    assert controller.start(action)
    assert entered.wait(3)
    assert not controller.start(action)  # spam clicks cannot overlap admin steps
    assert window._attaching
    d.close()
    d.deleteLater()
    qapp.sendPostedEvents(None, QEvent.DeferredDelete)
    gate.set()
    wait(qapp, lambda: not controller.running)
    assert calls == [('Test mic', clean)]
    assert not window._attaching and len(refreshed) == 1


@pytest.mark.parametrize('state,error', [('outdated', None), ('ready', 'Permission refused')])
def test_failed_repair_never_reports_success(window, qapp, monkeypatch, state, error):  # noqa: F811
    window.cfg.mic_device = 'Test mic'
    monkeypatch.setattr(window, '_when_devices_free', lambda fn: None)
    monkeypatch.setattr(window, 'toast', lambda *a: None)
    monkeypatch.setattr(dm, 'install', lambda *a, **kw: error)
    monkeypatch.setattr(dm, 'status', lambda mic=None: state)
    d = SettingsDialog(window, 'audio')
    card = d.findChild(RecoveryCard)
    assert card.recovery.start('repair')
    wait(qapp, lambda: not card.recovery.running)
    assert card.note.text() != 'Mic effect reinstalled. Test it in your voice chat.'
    assert card.note.text() and not window._attaching
    d.close()


def test_remove_verifies_effect_is_gone(window, qapp, monkeypatch):  # noqa: F811
    monkeypatch.setattr(window, '_when_devices_free', lambda fn: None)
    monkeypatch.setattr(dm, 'uninstall', lambda: None)
    monkeypatch.setattr(dm, 'status', lambda mic=None: 'missing')
    monkeypatch.setattr(dm, 'anything_installed', lambda: False)
    d = SettingsDialog(window, 'audio')
    card = d.findChild(RecoveryCard)
    assert card.recovery.start('remove')
    wait(qapp, lambda: not card.recovery.running)
    assert card.note.text() == 'Mic effect removed'
    assert window.cfg.route == 'cable'  # recovery does not switch the selected route
    d.close()


def test_clean_install_preflights_replacement_and_preserves_failed_removal(monkeypatch, tmp_path):
    dll = tmp_path / 'missing.dll'
    calls = []
    monkeypatch.setattr(dm, 'bundled_dll', lambda: dll)
    monkeypatch.setattr(dm, 'admin_uninstall', lambda: calls.append('remove') or 1)
    monkeypatch.setattr(dm, 'admin_install', lambda guid: calls.append('install') or 0)
    assert dm.admin_reinstall('guid') == 3
    assert not calls
    dll.write_bytes(b'')
    assert dm.admin_reinstall('guid') == 3
    assert not calls
    dll.write_bytes(b'dll')
    assert dm.admin_reinstall('guid') == 1
    assert calls == ['remove']  # failed removal keeps recovery notes; never install over it
    monkeypatch.setattr(dm, 'admin_uninstall', lambda: calls.append('remove') or 0)
    assert dm.admin_reinstall('guid') == 0
    assert calls[-2:] == ['remove', 'install']


@pytest.mark.parametrize('action', ['install', 'uninstall'])
def test_refusal_to_stop_audio_changes_nothing(monkeypatch, tmp_path, action):  # noqa: F811
    dll = tmp_path / 'obmic.dll'
    dll.write_bytes(b'dll')
    calls = []
    monkeypatch.setattr(dm, 'bundled_dll', lambda: dll)
    monkeypatch.setattr(dm, '_enable_privileges', lambda *a: None)
    monkeypatch.setattr(dm, '_running_dependents', lambda: [])
    monkeypatch.setattr(dm, '_audio_comes_back', lambda deps: None)
    monkeypatch.setattr(dm, '_audio_service', lambda start, deps=(): calls.append(start) or start)
    monkeypatch.setattr(dm, '_register_com', lambda *a: pytest.fail('registration changed'))
    monkeypatch.setattr(dm, 'installed_on', lambda: pytest.fail('mic settings touched'))
    result = dm.admin_install('guid') if action == 'install' else dm.admin_uninstall()
    assert result == 6
    assert calls == [False, True]  # restart is attempted even after a stop fails


def test_clean_reinstall_uses_one_admin_prompt(monkeypatch, tmp_path):
    dll = tmp_path / 'obmic.dll'
    dll.write_bytes(b'dll')
    calls = []
    monkeypatch.setattr(dm, 'bundled_dll', lambda: dll)
    monkeypatch.setattr(dm, 'endpoint_for', lambda mic: 'guid')
    monkeypatch.setattr(dm, '_elevated', lambda args: calls.append(args) or 0)
    assert dm.install('Test mic', clean=True) is None
    assert calls == [['reinstall', 'guid']]


def test_update_action_and_compact_secondary_buttons(window, qapp, monkeypatch):  # noqa: F811
    monkeypatch.setattr(dm, 'status', lambda mic=None: 'outdated')
    d = SettingsDialog(window, 'audio')
    d.resize(1180, 720)
    d.show()
    card = d.findChild(RecoveryCard)
    card._checked('outdated')
    for _i in range(5):
        qapp.processEvents()
    assert card.repair.text() == 'Update to new version'
    assert all(b.isVisibleTo(card) for b in card.actions.values())
    assert card.repair.height() > card.actions['reinstall'].height()
    assert card.repair.height() > card.actions['remove'].height()
    assert card.repair.property('recoveryUpdate')
    assert card.repair.graphicsEffect() is not None
    centers = [b.geometry().center().y() for b in card.actions.values()]
    assert max(centers) - min(centers) <= 1
    card.repair.click()
    assert card.dialog.windowTitle() == 'Update mic effect'
    buttons = card.dialog.findChildren(QPushButton)
    assert len({(b.width(), b.height()) for b in buttons}) == 1
    card.dialog.reject()
    card._checked('ready')
    assert not card.repair.isVisibleTo(card)
    assert card.actions['reinstall'].isVisibleTo(card)
    assert card.actions['remove'].isVisibleTo(card)
    d.close()
