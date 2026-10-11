"""Recovery must preserve a usable mic through failed and interrupted updates."""
import threading
import time

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QLabel, QPushButton

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


@pytest.mark.parametrize('state,pill,fix', [
    ('ready', 'Ready', None),
    ('outdated', 'Update available', 'Update mic effect'),
    ('wiped', 'Off', 'Repair mic effect'),  # Windows took it off: the fix must be on show
    ('other', 'Off', 'Repair mic effect'),
    ('missing', 'Off', None),
])
def test_card_offers_the_fix_each_state_needs(window, qapp, monkeypatch, state, pill, fix):  # noqa: F811
    monkeypatch.setattr(dm, 'status', lambda mic=None: state)
    window.resize(1180, 720)
    window.show()
    d = window.open_settings('audio')   # a page in the window, as the cog opens it
    card = d.findChild(RecoveryCard)
    card._checked(state)
    for _i in range(5):
        qapp.processEvents()
    assert card.pill.isVisibleTo(card) and card.pill.text() == pill
    # the heading has no top padding, so its words share a centre line with the pill
    assert card.heading.property('head')
    title, badge = card.heading.geometry(), card.pill.geometry()
    assert abs(title.center().y() - badge.center().y()) <= 1
    assert card.fix.isVisibleTo(card) == (fix is not None)
    if fix:
        assert card.fix.text() == fix and card.fix.graphicsEffect() is None
    # the rare actions live behind the ⋯ menu, never as a row of small buttons
    assert card.more.toolTip() and card.more.accessibleName()
    assert [a.text() for a in card.menu.actions() if not a.isSeparator()] == [
        'Repair mic effect', 'Clean reinstall', 'Remove mic effect']
    assert card.menu_actions['remove'].isEnabled() == (state != 'missing')
    assert not [b for b in card.findChildren(QPushButton) if b.objectName() == 'small']
    d.close()


def test_confirmation_follows_the_dialog_recipe(window, qapp, monkeypatch):  # noqa: F811
    monkeypatch.setattr(dm, 'status', lambda mic=None: 'outdated')
    d = SettingsDialog(window, 'audio')
    d.show()
    card = d.findChild(RecoveryCard)
    card._checked('outdated')
    card.fix.click()
    dialog = card.dialog
    assert dialog.windowTitle() == 'Update mic effect' and dialog.isModal()
    go, cancel = [b for b in dialog.findChildren(QPushButton)]
    assert go.text() == 'Update mic effect' and go.isDefault() and cancel.text() == 'Cancel'
    # buttons as wide as their words (German is 30% longer): no fixed sizes
    assert go.minimumWidth() == 0 and go.maximumWidth() > 10000
    dialog.reject()
    card._checked('ready')
    assert not card.fix.isVisibleTo(card)
    d.close()


@pytest.mark.parametrize('error', [None, 'Permission refused'])
def test_fix_plays_the_setup_show_and_outlines_working(window, qapp, monkeypatch, error):  # noqa: F811
    gate = threading.Event()
    window.cfg.mic_device = 'Test mic'
    monkeypatch.setattr(window, '_when_devices_free', lambda fn: None)
    monkeypatch.setattr(window, 'toast', lambda *a: None)
    monkeypatch.setattr(dm, 'status', lambda mic=None: 'ready')
    monkeypatch.setattr(dm, 'install', lambda *a, **kw: gate.wait(5) and error)
    window.show()
    d = window.open_settings('audio')   # a page in the window, as the cog opens it
    card = d.findChild(RecoveryCard)
    card.confirm('repair')
    next(b for b in card.dialog.findChildren(QPushButton)
         if b.text() == 'Repair mic effect').click()
    assert card.show_.on and card.show_.isVisibleTo(card)
    # Working… is a neutral pill with an outline, not loose text beside the heading
    assert card.pill.text() == 'Working…' and card.pill.property('tone') == 'muted'
    gate.set()
    wait(qapp, lambda: not card.recovery.running)
    assert card.show_._result is (error is None)   # its ending plays once far enough
    d.close()


# ---------------------------------------------------------------- more than one mic

GUID_A = '{0.0.1.00000000}.{aaaaaaaa-0000-0000-0000-000000000001}'
GUID_B = '{0.0.1.00000000}.{bbbbbbbb-0000-0000-0000-000000000002}'
GUID_C = '{0.0.1.00000000}.{cccccccc-0000-0000-0000-000000000003}'


def two_mics(a='ready', b='other', c=None):
    """Two plugged-in mics with the same name (a headset and its twin), and maybe an
    unplugged third."""
    out = [{'guid': GUID_A, 'name': 'Headset Mic (USB)', 'active': True, 'state': a,
            'pa': 'Headset Mic (USB)'},
           {'guid': GUID_B, 'name': 'Headset Mic (USB)', 'active': True, 'state': b,
            'pa': 'Headset Mic (USB) #2'}]
    if c:
        out.append({'guid': GUID_C, 'name': 'Old Mic', 'active': False, 'state': c,
                    'pa': None})
    return out


def card_with(window, qapp, monkeypatch, found):  # noqa: F811
    window.cfg.mic_device = 'Headset Mic (USB)'
    monkeypatch.setattr(dm, 'mics', lambda names=(): [dict(m) for m in found])
    monkeypatch.setattr(dm, 'status', lambda mic=None: found[0]['state'])
    window.show()
    d = window.open_settings('audio')   # a page in the window: a hidden card doesn't check
    card = d.findChild(RecoveryCard)
    card.check()
    wait(qapp, lambda: card.target_box.count() == len(found) and not card._checking)
    return d, card


def pick(card, guid):
    card.target_box.setCurrentIndex(card.target_box.findData(guid))
    card.target_box.activated.emit(card.target_box.currentIndex())


def test_card_names_the_mic_and_starts_on_the_one_in_use(window, qapp, monkeypatch):  # noqa: F811
    d, card = card_with(window, qapp, monkeypatch, two_mics())
    box = card.target_box
    # the same name twice is told apart; the list starts on the mic the app sends into
    assert [box.itemText(i) for i in range(box.count())] == [
        'Headset Mic (USB)', 'Headset Mic (USB) (2)']
    assert box.currentData() == GUID_A and box.accessibleName() == 'Mic to fix'
    assert box.property('noWheel')
    assert card.pill.text() == 'Ready' and not card.fix.isVisibleTo(card)
    d.close()


def test_each_mic_keeps_its_own_state(window, qapp, monkeypatch):  # noqa: F811
    d, card = card_with(window, qapp, monkeypatch, two_mics('ready', 'other'))
    pick(card, GUID_B)
    assert card.pill.text() == 'Off' and card.fix.text() == 'Repair mic effect'
    assert not card.menu_actions['remove'].isEnabled()   # nothing to remove on this one
    # says where the effect is, instead of leaving it to be guessed
    assert card.where.isVisibleTo(card) and 'Headset Mic (USB)' in card.where.text()
    pick(card, GUID_A)
    assert card.pill.text() == 'Ready' and card.menu_actions['remove'].isEnabled()
    assert not card.where.isVisibleTo(card)
    # a re-check keeps the mic that was picked, even though the app's mic is the other
    pick(card, GUID_B)
    card.check()
    wait(qapp, lambda: not card._checking)
    assert card.target_box.currentData() == GUID_B and card.pill.text() == 'Off'
    d.close()


def test_repair_acts_only_on_the_picked_mic(window, qapp, monkeypatch):  # noqa: F811
    calls, switched = [], []
    d, card = card_with(window, qapp, monkeypatch, two_mics('ready', 'other'))
    monkeypatch.setattr(dm, 'install_on', lambda guid, clean=False: calls.append(guid))
    monkeypatch.setattr(dm, 'install', lambda *a, **k: pytest.fail('went by name'))
    monkeypatch.setattr(dm, 'status_on', lambda guid: 'ready')
    monkeypatch.setattr(window, '_when_devices_free', lambda fn: None)
    monkeypatch.setattr(window, 'on_device', lambda cb, attr: switched.append(attr))
    window.cb_mic.addItem('Headset Mic (USB) #2', 'Headset Mic (USB) #2')
    pick(card, GUID_B)
    card.confirm('repair')
    words = ' '.join(lbl.text() for lbl in card.dialog.findChildren(QLabel))
    # the dialog names the mic, says the effect moves, and that sounds go there now
    assert 'Headset Mic (USB) (2)' in words and 'comes off Headset Mic (USB)' in words
    assert 'send your sounds into Headset Mic (USB) (2)' in words
    next(b for b in card.dialog.findChildren(QPushButton)
         if b.text() == 'Repair mic effect').click()
    wait(qapp, lambda: not card.recovery.running)
    assert calls == [GUID_B]
    assert switched == ['mic_device']   # the app now sends into the mic it went on
    assert window.cb_mic.currentData() == 'Headset Mic (USB) #2'
    assert card.note.text() == ('Mic effect reinstalled on Headset Mic (USB) (2). '
                                'Test it in your voice chat.')
    d.close()


def test_remove_leaves_the_other_mic_alone(window, qapp, monkeypatch):  # noqa: F811
    calls = []
    d, card = card_with(window, qapp, monkeypatch, two_mics('ready', 'ready'))
    monkeypatch.setattr(dm, 'uninstall', lambda guid=None: calls.append(guid))
    monkeypatch.setattr(dm, 'status_on', lambda guid: 'other')
    monkeypatch.setattr(window, '_when_devices_free', lambda fn: None)
    pick(card, GUID_B)
    card.confirm('remove')
    next(b for b in card.dialog.findChildren(QPushButton)
         if b.text() == 'Remove mic effect').click()
    wait(qapp, lambda: not card.recovery.running)
    assert calls == [GUID_B]
    assert card.note.text() == 'Mic effect removed from Headset Mic (USB) (2)'
    d.close()


def test_unplugged_mic_is_listed_but_never_repaired(window, qapp, monkeypatch):  # noqa: F811
    d, card = card_with(window, qapp, monkeypatch, two_mics('other', 'other', 'ready'))
    monkeypatch.setattr(dm, 'install_on', lambda *a, **k: pytest.fail('repaired unplugged'))
    monkeypatch.setattr(window, 'toast', lambda *a: None)
    assert card.target_box.itemText(2) == 'Old Mic (unplugged)'
    pick(card, GUID_C)
    assert not card.fix.isVisibleTo(card)
    assert not card.menu_actions['repair'].isEnabled()
    assert not card.menu_actions['reinstall'].isEnabled()
    assert card.menu_actions['remove'].isEnabled()   # the effect can still come off it
    assert card.where.text() == 'Plug this mic in to repair it.'
    assert not card.recovery.start('repair', card.target())
    assert not card.recovery.running and not window._attaching
    d.close()


def test_mic_list_by_endpoint(monkeypatch):
    monkeypatch.setattr(dm, 'capture_endpoints', lambda: [
        {'guid': GUID_A, 'name': 'Mic (USB)', 'active': True},
        {'guid': GUID_B, 'name': 'Mic (USB)', 'active': True},
        {'guid': GUID_C, 'name': 'Gone (USB)', 'active': False},
        {'guid': '{x}', 'name': 'Old headset', 'active': False}])
    monkeypatch.setattr(dm, 'installed_on', lambda: [GUID_B, GUID_C])
    monkeypatch.setattr(dm, 'effect_in_place', lambda guid: True)
    monkeypatch.setattr(dm, 'make_ring', lambda: True)
    monkeypatch.setattr(dm, 'same_dll', lambda *a: True)
    monkeypatch.setattr(dm, 'registered_dll', lambda: None)
    monkeypatch.setattr(dm, 'installed_slot', lambda guid: None)
    found = dm.mics(['Mic (USB)'])
    # unplugged without the effect: left out; unplugged with it: kept, last
    assert [(m['guid'], m['state']) for m in found] == [
        (GUID_A, 'other'), (GUID_B, 'ready'), (GUID_C, 'ready')]
    assert not found[2]['active']
    # a name two mics share can't be told apart: neither is matched to it
    assert [m['pa'] for m in found] == [None, None, None]
    assert dm.status_on(GUID_B) == 'ready' and dm.status_on(GUID_A) == 'other'


def test_uninstall_one_mic_keeps_the_rest(monkeypatch):
    on = [GUID_A, GUID_B]
    gone, steps = [], []
    monkeypatch.setattr(dm, '_enable_privileges', lambda *a: None)
    monkeypatch.setattr(dm, '_running_dependents', lambda: [])
    monkeypatch.setattr(dm, '_audio_comes_back', lambda deps: None)
    monkeypatch.setattr(dm, '_audio_service', lambda start, deps=(): True)
    monkeypatch.setattr(dm, 'installed_on', lambda: list(on))
    monkeypatch.setattr(dm, '_uninstall_endpoint', lambda g: (gone.append(g), on.remove(g)))
    monkeypatch.setattr(dm, '_unregister_com', lambda: steps.append('unregister'))
    monkeypatch.setattr(dm, '_remove', lambda path: steps.append('files'))
    assert dm.admin_uninstall(GUID_B) == 0
    assert gone == [GUID_B] and on == [GUID_A] and not steps   # still used by mic A
    assert dm.admin_uninstall(GUID_A) == 0
    assert gone == [GUID_B, GUID_A] and 'unregister' in steps   # the last one: all gone


def test_uninstall_one_mic_from_the_command_line(monkeypatch):
    asked = []
    monkeypatch.setattr(dm, '_elevated', lambda args: asked.append(args) or 0)
    assert dm.uninstall('{0.0.1.00000000}.{bbbbbbbb-0000-0000-0000-000000000002}') is None
    assert asked == [['uninstall', GUID_B]]
    assert dm.uninstall() is None and asked[-1] == ['uninstall']


def test_twin_the_app_cant_switch_to_says_where_sounds_go(window, qapp, monkeypatch):  # noqa: F811
    found = two_mics('ready', 'other')
    found[1]['pa'] = None   # its name is shared: the app can't pick it by itself
    d, card = card_with(window, qapp, monkeypatch, found)
    pick(card, GUID_B)
    card.confirm('repair')
    words = ' '.join(lbl.text() for lbl in card.dialog.findChildren(QLabel))
    assert 'Your sounds go into Headset Mic (USB). To use this mic instead' in words
    assert 'from now on' not in words
    card.dialog.reject()
    d.close()
