"""Recovery must preserve a usable mic through failed and interrupted updates."""
import threading
import time

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QCheckBox, QComboBox, QLabel, QPushButton

from soundboard.mic import directmic as dm
from soundboard.ui.settings.settings import SettingsDialog
from soundboard.ui.setup.audiorecovery import RecoveryCard
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
    monkeypatch.setattr(dm, '_elevated', lambda *a, **k: asked.append(a))
    d = SettingsDialog(window, 'audio')
    card = d.findChild(RecoveryCard)
    card.confirm(action, card.shown()[0])
    card.confirm(action, card.shown()[0])  # repeated clicks keep the same confirmation
    assert card.dialog.isVisible()
    next(b for b in card.dialog.findChildren(QPushButton) if b.text() == 'Cancel').click()
    assert not asked and not card.recovery.running
    d.close()


@pytest.mark.parametrize('action,clean', [('repair', False), ('reinstall', True), ('update', True)])
def test_recovery_finishes_after_settings_is_deleted(window, qapp, monkeypatch, action, clean):  # noqa: F811
    gate, entered = threading.Event(), threading.Event()
    calls, refreshed = [], []
    window.cfg.mic_device = 'Test mic'
    monkeypatch.setattr(window.devctl, '_when_devices_free', lambda fn: refreshed.append(fn))
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
    monkeypatch.setattr(window.devctl, '_when_devices_free', lambda fn: None)
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


@pytest.mark.parametrize('result,state,counted', [
    (lambda: dm.Failure('Installing failed (code 8).', 'code-8'), 'missing',
     {'recovery-repair', 'recovery-failed', 'recovery-failed-code-8'}),
    (lambda: dm.Failure(dm.declined(), 'said-no'), 'outdated',
     {'recovery-repair', 'recovery-said-no'}),
    (lambda: None, 'outdated',
     {'recovery-repair', 'recovery-failed', 'recovery-failed-unverified'}),
    (lambda: 'some other text', 'missing',
     {'recovery-repair', 'recovery-failed', 'recovery-failed-code-other'}),
])
def test_failed_fix_counts_why(window, qapp, monkeypatch, result, state, counted):  # noqa: F811
    """The card's failure count carries a fixed reason word, and No to Windows' prompt
    isn't a failure."""
    from soundboard.core import usage
    sent = []
    monkeypatch.setattr(usage, 'used', sent.append)
    window.cfg.mic_device = 'Test mic'
    monkeypatch.setattr(window.devctl, '_when_devices_free', lambda fn: None)
    monkeypatch.setattr(window, 'toast', lambda *a, **k: None)
    monkeypatch.setattr(dm, 'install', lambda *a, **kw: result())
    monkeypatch.setattr(dm, 'status', lambda mic=None: state)
    from soundboard.ui.setup.audiorecovery import recovery_of
    rec = recovery_of(window)
    assert rec.start('repair')
    wait(qapp, lambda: not rec.running)
    assert set(sent) == counted
    assert set(sent) <= set(usage.FEATURES)


def test_crashed_fix_counts_error(window, qapp, monkeypatch):  # noqa: F811
    from soundboard.core import usage
    from soundboard.ui.setup.audiorecovery import recovery_of
    sent = []
    monkeypatch.setattr(usage, 'used', sent.append)
    window.cfg.mic_device = 'Test mic'
    monkeypatch.setattr(window.devctl, '_when_devices_free', lambda fn: None)
    monkeypatch.setattr(window, 'toast', lambda *a, **k: None)

    def boom(*a, **kw):
        raise OSError('device gone')
    monkeypatch.setattr(dm, 'install', boom)
    rec = recovery_of(window)
    assert rec.start('reinstall')
    wait(qapp, lambda: not rec.running)
    assert set(sent) == {'recovery-reinstall', 'recovery-failed', 'recovery-failed-error'}


def test_remove_verifies_effect_is_gone(window, qapp, monkeypatch):  # noqa: F811
    monkeypatch.setattr(window.devctl, '_when_devices_free', lambda fn: None)
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
    monkeypatch.setattr(dm, '_audio_off', lambda work, also=(): work())
    monkeypatch.setattr(dm, '_take_off', lambda only: calls.append('remove') or 1)
    monkeypatch.setattr(dm, '_put_on', lambda guid, slot, dll: calls.append('install') or 0)
    monkeypatch.setattr(dm, 'registered_dll', lambda: None)
    assert dm.admin_reinstall('guid') == 3
    assert not calls
    dll.write_bytes(b'')
    assert dm.admin_reinstall('guid') == 3
    assert not calls
    dll.write_bytes(b'dll')
    assert dm.admin_reinstall('guid') == 1
    assert calls == ['remove']  # failed removal keeps recovery notes; never install over it
    monkeypatch.setattr(dm, '_take_off', lambda only: calls.append('remove') or 0)
    assert dm.admin_reinstall('guid') == 0
    assert calls[-2:] == ['remove', 'install']


@pytest.mark.parametrize('fails,result,sources', [
    (0, 0, ['new']),                      # goes on first time
    (1, 0, ['new', 'new']),               # a second try works
    (2, 6, ['new', 'new', 'old']),        # won't go on: the old part goes back
])
def test_clean_reinstall_never_leaves_the_mic_without_a_part(monkeypatch, tmp_path, fails,
                                                             result, sources):
    new, old = tmp_path / 'obmic.dll', tmp_path / 'obmic-old.dll'
    new.write_bytes(b'new')
    old.write_bytes(b'old')
    data = tmp_path / 'OnionBoard' / 'MicPlugin'
    data.mkdir(parents=True)
    tried = []

    def install(guid, slot, source):
        tried.append('new' if source == new else 'old')
        if source != new:
            assert source.read_bytes() == b'old'   # a copy kept before the uninstall
            return 0
        if tried.count('new') <= fails:
            if fails == 2 and tried.count('new') == 1:
                raise OSError('registry')   # an exception counts as a failure too
            return 6
        return 0
    monkeypatch.setattr(dm, 'bundled_dll', lambda: new)
    monkeypatch.setattr(dm, 'registered_dll', lambda: old)
    monkeypatch.setattr(dm, 'installed_on', lambda: ['guid'])
    monkeypatch.setattr(dm, 'data_dir', lambda: data)
    monkeypatch.setattr(dm, '_take_off', lambda only: old.unlink() or 0)   # old part gone
    monkeypatch.setattr(dm, '_put_on', install)
    monkeypatch.setattr(dm.time, 'sleep', lambda s: None)
    stops = []
    monkeypatch.setattr(dm, '_audio_off', lambda work, also=(): stops.append(1) or work())
    assert dm.admin_reinstall('guid') == result
    assert tried == sources
    assert stops == [1]   # one restart of Windows' audio for the whole job, retries too
    assert not list(data.parent.glob('obmic-previous*'))   # the copy doesn't stay


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
    # (reading which mics have it is fine: the mics are listened to before the step)
    monkeypatch.setattr(dm, 'installed_on', lambda: [])
    # (something of it is there: with nothing at all an uninstall leaves the audio alone)
    monkeypatch.setattr(dm, 'anything_installed', lambda: True)
    monkeypatch.setattr(dm, '_put_on', lambda *a: pytest.fail('mic settings touched'))
    monkeypatch.setattr(dm, '_take_off', lambda *a: pytest.fail('mic settings touched'))
    result = dm.admin_install('guid') if action == 'install' else dm.admin_uninstall()
    assert result == 6
    assert calls == [False, True]  # restart is attempted even after a stop fails


def test_clean_reinstall_uses_one_admin_prompt(monkeypatch, tmp_path):
    dll = tmp_path / 'obmic.dll'
    dll.write_bytes(b'dll')
    calls = []
    monkeypatch.setattr(dm, 'bundled_dll', lambda: dll)
    monkeypatch.setattr(dm, 'endpoint_for', lambda mic: 'guid')
    monkeypatch.setattr(dm, '_elevated', lambda args, **k: calls.append(args) or 0)
    assert dm.install('Test mic', clean=True) is None
    assert calls == [['reinstall', 'guid']]


@pytest.mark.parametrize('state,pill,buttons', [
    ('ready', 'Ready', ['Clean reinstall', 'Remove mic effect']),
    ('outdated', 'Update available', ['Update mic effect', 'Clean reinstall', 'Remove mic effect']),
    # Windows took it off: the fix must be on show
    ('wiped', 'Off', ['Repair mic effect', 'Clean reinstall', 'Remove mic effect']),
    # not on this mic: nothing to repair or remove, it's installed
    ('other', 'Not installed', ['Install mic effect']),
    ('missing', 'Not installed', ['Install mic effect']),
])
def test_card_offers_the_fix_each_state_needs(window, qapp, monkeypatch, state, pill, buttons):  # noqa: F811
    monkeypatch.setattr(dm, 'status', lambda mic=None: state)
    window.cfg.route = 'mic'   # (the rows are about the mic sent into)
    window.resize(1180, 720)
    window.show()
    d = window.setctl.open_settings('audio')   # a page in the window, as the cog opens it
    card = d.findChild(RecoveryCard)
    card._checked(state)
    for _i in range(5):
        qapp.processEvents()
    row = card.rows[None]   # Windows listed no mics: the app's mic on its own
    assert row.pill.isVisibleTo(row) and row.pill.text() == pill
    # every action is a button on the mic's own row: no ⋯ menu, no dropdown
    assert [b.text() for b in row.buttons.values()] == buttons
    assert all(b.isVisibleTo(card) for b in row.buttons.values())
    assert not card.findChildren(QComboBox)
    assert not [b for b in card.findChildren(QPushButton) if b.objectName() == 'iconbutton']
    filled = [b for b in row.buttons.values() if b.objectName() == 'primary']
    assert len(filled) <= 1 and all(b.graphicsEffect() is None for b in filled)
    assert not [b for b in card.findChildren(QPushButton) if b.objectName() == 'small']
    # sent through the cable: a mic without the effect isn't listed (nothing to do there)
    window.cfg.route = 'cable'
    card._rebuild()
    on_mic = state in ('ready', 'outdated', 'wiped')
    assert bool(card.rows) == on_mic
    assert card.not_mic.isVisibleTo(card) != on_mic   # how to switch, instead
    assert card.new_mic.isVisibleTo(card) == on_mic
    d.close()


def test_confirmation_follows_the_dialog_recipe(window, qapp, monkeypatch):  # noqa: F811
    monkeypatch.setattr(dm, 'status', lambda mic=None: 'outdated')
    d = SettingsDialog(window, 'audio')
    d.show()
    card = d.findChild(RecoveryCard)
    card._checked('outdated')
    card.rows[None].buttons['update'].click()
    dialog = card.dialog
    assert dialog.windowTitle() == 'Update mic effect' and dialog.isModal()
    go, cancel = [b for b in dialog.findChildren(QPushButton)]
    assert go.text() == 'Update mic effect' and go.isDefault() and cancel.text() == 'Cancel'
    # buttons as wide as their words (German is 30% longer): no fixed sizes
    assert go.minimumWidth() == 0 and go.maximumWidth() > 10000
    dialog.reject()
    card._checked('ready')
    assert 'update' not in card.rows[None].buttons
    d.close()


@pytest.mark.parametrize('error', [None, 'Permission refused'])
def test_fix_plays_the_setup_show_and_outlines_working(window, qapp, monkeypatch, error):  # noqa: F811
    gate = threading.Event()
    window.cfg.mic_device = 'Test mic'
    monkeypatch.setattr(window.devctl, '_when_devices_free', lambda fn: None)
    monkeypatch.setattr(window, 'toast', lambda *a: None)
    monkeypatch.setattr(dm, 'status', lambda mic=None: 'ready')
    monkeypatch.setattr(dm, 'install', lambda *a, **kw: gate.wait(5) and error)
    window.show()
    d = window.setctl.open_settings('audio')   # a page in the window, as the cog opens it
    card = d.findChild(RecoveryCard)
    card.confirm('repair', card.shown()[0])
    next(b for b in card.dialog.findChildren(QPushButton)
         if b.text() == 'Repair mic effect').click()
    assert card.show_.on and card.show_.isVisibleTo(card)
    # Working… is a neutral pill with an outline, not loose text beside the heading
    assert card.pill.text() == 'Working…' and card.pill.property('tone') == 'muted'
    gate.set()
    wait(qapp, lambda: not card.recovery.running)
    assert card.show_._result is (error is None)   # its ending plays once far enough
    assert not card.pill.isVisibleTo(card)
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
    d = window.setctl.open_settings('audio')   # a page in the window: a hidden card doesn't check
    card = d.findChild(RecoveryCard)
    card.check()
    wait(qapp, lambda: len(card.rows) == len(found) and not card._checking)
    return d, card


def texts(row):
    return [b.text() for b in row.buttons.values()]


def test_every_mic_is_a_row_with_its_name_and_state(window, qapp, monkeypatch):  # noqa: F811
    d, card = card_with(window, qapp, monkeypatch, two_mics())
    a, b = card.rows[GUID_A], card.rows[GUID_B]
    # twins are numbered (in front); the mic the app sends into says so
    assert (a.name.text(), b.name.text()) == ('#1 Headset Mic (USB)', '#2 Headset Mic (USB)')
    assert a.in_use.isVisibleTo(a) and not b.in_use.isVisibleTo(b)
    assert a.pill.text() == 'Ready' and texts(a) == ['Clean reinstall', 'Remove mic effect']
    # the pills sit right after the name, on its line, not at the far edge of the row
    assert 0 <= a.pill.x() - a.name.geometry().right() <= 12
    assert a.name.height() < 2 * a.name.fontMetrics().height()
    assert not card.findChildren(QComboBox)
    d.close()


def test_each_mic_keeps_its_own_state(window, qapp, monkeypatch):  # noqa: F811
    d, card = card_with(window, qapp, monkeypatch, two_mics('ready', 'other'))
    b = card.rows[GUID_B]
    assert b.pill.text() == 'Not installed'
    # nothing to repair, reinstall or remove there: install it, or clean up leftovers
    assert texts(b) == ['Install mic effect', 'Clean up leftovers']
    assert card.rows[GUID_A].pill.text() == 'Ready'
    # a re-check that changed nothing keeps the rows (and keyboard focus in them)
    card.check()
    wait(qapp, lambda: not card._checking)
    assert card.rows[GUID_B] is b
    d.close()


def test_install_acts_only_on_that_mic(window, qapp, monkeypatch):  # noqa: F811
    calls, switched = [], []
    d, card = card_with(window, qapp, monkeypatch, two_mics('ready', 'other'))
    monkeypatch.setattr(dm, 'install_on', lambda guid, clean=False: calls.append(guid))
    monkeypatch.setattr(dm, 'install', lambda *a, **k: pytest.fail('went by name'))
    monkeypatch.setattr(dm, 'status_on', lambda guid: 'ready')
    monkeypatch.setattr(window.devctl, '_when_devices_free', lambda fn: None)
    monkeypatch.setattr(window.routectl, 'on_device', lambda cb, attr: switched.append(attr))
    window.cb_mic.addItem('Headset Mic (USB) #2', 'Headset Mic (USB) #2')
    card.rows[GUID_B].buttons['install'].click()
    assert card.dialog.windowTitle() == 'Install mic effect'
    words = ' '.join(lbl.text() for lbl in card.dialog.findChildren(QLabel))
    # the dialog names the mic, says the effect moves, and that sounds go there now
    assert "mic effect on #2 Headset Mic (USB)" in words
    assert 'comes off #1 Headset Mic (USB)' in words
    assert 'send your sounds into #2 Headset Mic (USB)' in words
    next(b for b in card.dialog.findChildren(QPushButton)
         if b.text() == 'Install mic effect').click()
    wait(qapp, lambda: not card.recovery.running)
    assert calls == [GUID_B]
    assert switched == ['mic_device']   # the app now sends into the mic it went on
    assert window.cb_mic.currentData() == 'Headset Mic (USB) #2'
    assert card.note.text() == ('Mic effect installed on #2 Headset Mic (USB). '
                                'Test it in your voice chat.')
    d.close()


def test_remove_leaves_the_other_mic_alone(window, qapp, monkeypatch):  # noqa: F811
    calls = []
    d, card = card_with(window, qapp, monkeypatch, two_mics('ready', 'ready'))
    monkeypatch.setattr(dm, 'uninstall', lambda guid=None: calls.append(guid))
    monkeypatch.setattr(dm, 'status_on', lambda guid: 'other')
    monkeypatch.setattr(window.devctl, '_when_devices_free', lambda fn: None)
    card.rows[GUID_B].buttons['remove'].click()
    next(b for b in card.dialog.findChildren(QPushButton)
         if b.text() == 'Remove mic effect').click()
    wait(qapp, lambda: not card.recovery.running)
    assert calls == [GUID_B]
    assert card.note.text() == 'Mic effect removed from #2 Headset Mic (USB)'
    d.close()


def test_unplugged_mic_is_listed_but_never_repaired(window, qapp, monkeypatch):  # noqa: F811
    d, card = card_with(window, qapp, monkeypatch, two_mics('other', 'other', 'wiped'))
    monkeypatch.setattr(dm, 'install_on', lambda *a, **k: pytest.fail('repaired unplugged'))
    monkeypatch.setattr(window, 'toast', lambda *a: None)
    c = card.rows[GUID_C]
    assert c.name.text() == 'Old Mic (unplugged)'
    assert texts(c) == ['Remove mic effect']   # the effect can still come off it
    assert c.hint.isVisibleTo(c) and c.hint.text() == 'Plug this mic in to repair it.'
    assert not card.recovery.start('repair', c.mic)
    assert not card.recovery.running and not window._attaching
    d.close()


def test_mic_list_by_endpoint(monkeypatch, tmp_path):
    monkeypatch.setattr(dm, 'capture_endpoints', lambda: [
        {'guid': GUID_A, 'name': 'Mic (USB)', 'active': True},
        {'guid': GUID_B, 'name': 'Mic (USB)', 'active': True},
        {'guid': GUID_C, 'name': 'Gone (USB)', 'active': False},
        {'guid': '{x}', 'name': 'Old headset', 'active': False}])
    monkeypatch.setattr(dm, 'installed_on', lambda: [GUID_B, GUID_C])
    monkeypatch.setattr(dm, 'effect_in_place', lambda guid: True)
    monkeypatch.setattr(dm, 'make_ring', lambda: True)
    monkeypatch.setattr(dm, 'same_dll', lambda *a: True)
    dll = tmp_path / 'obmic-1.dll'
    dll.write_bytes(b'dll')
    monkeypatch.setattr(dm, 'registered_dll', lambda: dll)
    monkeypatch.setattr(dm, 'installed_slot', lambda guid: None)
    found = dm.mics(['Mic (USB)'])
    # unplugged without the effect: left out; unplugged with it: kept, last
    assert [(m['guid'], m['state']) for m in found] == [
        (GUID_A, 'other'), (GUID_B, 'ready'), (GUID_C, 'ready')]
    assert not found[2]['active']
    # a name two mics share can't be told apart: neither is matched to it
    assert [m['pa'] for m in found] == [None, None, None]
    assert dm.status_on(GUID_B) == 'ready' and dm.status_on(GUID_A) == 'other'


def test_mic_list_leaves_out_virtual_cables(monkeypatch, tmp_path):
    cable, vm = '{cable}', '{voicemeeter}'
    monkeypatch.setattr(dm, 'capture_endpoints', lambda: [
        {'guid': GUID_A, 'name': 'Microphone (Logitech G733 Gaming Headset)', 'active': True},
        {'guid': cable, 'name': 'CABLE Output (VB-Audio Virtual Cable)', 'active': True},
        {'guid': vm, 'name': 'VoiceMeeter Output (VB-Audio VoiceMeeter VAIO)',
         'active': True}])
    on = []
    monkeypatch.setattr(dm, 'installed_on', lambda: list(on))
    monkeypatch.setattr(dm, 'effect_in_place', lambda guid: True)
    monkeypatch.setattr(dm, 'make_ring', lambda: True)
    monkeypatch.setattr(dm, 'same_dll', lambda *a: True)
    dll = tmp_path / 'obmic-1.dll'
    dll.write_bytes(b'dll')
    monkeypatch.setattr(dm, 'registered_dll', lambda: dll)
    monkeypatch.setattr(dm, 'installed_slot', lambda guid: None)
    # a cable's end records our own sounds: never offered the effect
    assert [m['guid'] for m in dm.mics()] == [GUID_A]
    # one that already has it (an older version put it there) stays, to take it off
    on.append(cable)
    assert [(m['guid'], m['state']) for m in dm.mics()] == [(cable, 'ready'), (GUID_A, 'other')]


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
    monkeypatch.setattr(dm, '_elevated', lambda args, **k: asked.append(args) or 0)
    assert dm.uninstall('{0.0.1.00000000}.{bbbbbbbb-0000-0000-0000-000000000002}') is None
    assert asked == [['uninstall', GUID_B]]
    assert dm.uninstall() is None and asked[-1] == ['uninstall']


def test_twin_the_app_cant_switch_to_says_where_sounds_go(window, qapp, monkeypatch):  # noqa: F811
    found = two_mics('ready', 'other')
    found[1]['pa'] = None   # its name is shared: the app can't pick it by itself
    d, card = card_with(window, qapp, monkeypatch, found)
    card.rows[GUID_B].buttons['install'].click()
    words = ' '.join(lbl.text() for lbl in card.dialog.findChildren(QLabel))
    assert 'Your sounds go into Headset Mic (USB). To use this mic instead' in words
    assert 'from now on' not in words
    card.dialog.reject()
    d.close()


# ---------------------------------------------------------------- leftovers on a mic

OTHER = '{11111111-2222-3333-4444-555555555555}'   # a driver's own effect


def test_without_ours_takes_only_our_effect_out():
    assert dm.without_ours([OTHER, dm.CLSID.lower()]) == (True, [OTHER])
    assert dm.without_ours([dm.CLSID]) == (True, None)
    assert dm.without_ours(dm.CLSID) == (True, None)
    assert dm.without_ours(OTHER) == (False, OTHER)
    assert dm.without_ours([OTHER]) == (False, [OTHER])


def test_strip_endpoint_leaves_everything_else(monkeypatch):
    changed = {}

    class Key:
        def __init__(self, path, create=True):
            assert path.endswith(GUID_B + r'\FxProperties') and not create

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            pass

        def set(self, name, kind, value):
            changed[name] = value

        def delete(self, name):
            changed[name] = 'deleted'
    monkeypatch.setattr(dm, '_BackupKey', Key)
    monkeypatch.setattr(dm, '_fx_values', lambda guid: {
        dm.FX % 5: dm.CLSID, dm.FX % 6: [OTHER, dm.CLSID], dm.FX % 7: OTHER})
    dm._strip_endpoint(GUID_B)
    assert changed == {dm.FX % 5: 'deleted', dm.FX % 6: [OTHER]}   # FX 7 untouched


def test_leftovers_reads_without_admin(monkeypatch):
    on, fx, rest = [], {}, [False]
    monkeypatch.setattr(dm, 'installed_on', lambda: list(on))
    monkeypatch.setattr(dm, '_fx_values', lambda guid: fx)
    monkeypatch.setattr(dm, 'anything_installed', lambda: rest[0])
    assert not dm.leftovers(GUID_B)
    fx[dm.FX % 5] = [OTHER, dm.CLSID]
    assert dm.leftovers(GUID_B)   # our effect in a slot without notes
    fx.clear()
    rest[0] = True
    assert dm.leftovers(GUID_B)   # on no mic, but still registered
    on.append(GUID_A)
    assert not dm.leftovers(GUID_B)   # mic A uses it: that's not a leftover


@pytest.mark.parametrize('on,traces,rest', [
    ([], True, True), ([GUID_A], True, True), ([], False, True), ([GUID_A], False, False)])
def test_admin_cleanup(monkeypatch, on, traces, rest):
    steps = []
    monkeypatch.setattr(dm, '_enable_privileges', lambda *a: None)
    monkeypatch.setattr(dm, '_running_dependents', lambda: [])
    monkeypatch.setattr(dm, '_audio_comes_back', lambda deps: None)
    monkeypatch.setattr(dm, '_audio_service', lambda start, deps=(): steps.append(start) or True)
    monkeypatch.setattr(dm, 'installed_on', lambda: list(on))
    monkeypatch.setattr(dm, '_fx_values', lambda guid: {dm.FX % 5: dm.CLSID} if traces else {})
    monkeypatch.setattr(dm, '_strip_endpoint', lambda guid: steps.append(('strip', guid)))
    monkeypatch.setattr(dm, 'anything_installed', lambda: rest)
    monkeypatch.setattr(dm, 'admin_uninstall', lambda only=None: steps.append(('all', only)) or 0)
    assert dm.admin_cleanup(GUID_B) == 0
    # the mic is only rewritten with Windows' audio stopped, and only if ours is on it
    assert steps[:3] == ([False, ('strip', GUID_B), True] if traces else steps[:3])
    if not traces:
        assert False not in steps
    # the effect itself only goes when no mic uses it
    assert (('all', None) in steps) == (not on and rest)


def test_admin_cleanup_of_a_mic_with_notes_is_a_normal_remove(monkeypatch):
    monkeypatch.setattr(dm, 'installed_on', lambda: [GUID_B])
    monkeypatch.setattr(dm, 'admin_uninstall', lambda only=None: 7 if only == GUID_B else 0)
    assert dm.admin_cleanup(GUID_B) == 7


def test_cleanup_from_the_command_line(monkeypatch):
    asked = []
    monkeypatch.setattr(dm, '_elevated', lambda args, **k: asked.append(args) or 0)
    assert dm.cleanup(GUID_B) is None and asked == [['cleanup', GUID_B]]


@pytest.mark.parametrize('found', [False, True])
def test_cleanup_asks_for_admin_only_when_something_is_there(window, qapp, monkeypatch, found):  # noqa: F811
    asked, switched = [], []
    d, card = card_with(window, qapp, monkeypatch, two_mics('ready', 'other'))
    left = [found]
    monkeypatch.setattr(dm, 'leftovers', lambda guid: left[0])
    monkeypatch.setattr(dm, 'cleanup',
                        lambda guid: asked.append(guid) or left.__setitem__(0, False))
    monkeypatch.setattr(dm, 'status_on', lambda guid: 'other')
    monkeypatch.setattr(window.devctl, '_when_devices_free', lambda fn: None)
    monkeypatch.setattr(window.routectl, 'on_device', lambda cb, attr: switched.append(attr))
    card.rows[GUID_B].buttons['cleanup'].click()
    words = ' '.join(lbl.text() for lbl in card.dialog.findChildren(QLabel))
    assert "Only Onion Board's own parts go" in words and 'comes off' not in words
    next(b for b in card.dialog.findChildren(QPushButton)
         if b.text() == 'Clean up leftovers').click()
    wait(qapp, lambda: not card.recovery.running)
    assert asked == ([GUID_B] if found else [])
    assert not switched   # cleaning up never moves your sounds to another mic
    assert card.note.text() == ('Leftovers removed from #2 Headset Mic (USB).' if found else
                                "Nothing of Onion Board's was left on #2 Headset Mic (USB).")
    d.close()


def test_a_new_card_shows_the_last_rows_at_once(window, qapp, monkeypatch):  # noqa: F811
    """Built empty, the card's rows came in after Settings was on screen and pushed the
    page down: a new card (Settings opened again, made afresh) starts with the rows
    the last look found, then looks again."""
    d, card = card_with(window, qapp, monkeypatch, two_mics())
    d.close()
    fresh = RecoveryCard(window)
    assert set(fresh.rows) == {GUID_A, GUID_B}   # before any look of its own
    fresh.deleteLater()


def test_the_first_look_runs_before_the_card_shows(window, qapp, monkeypatch):  # noqa: F811
    """Settings is built behind the loading screen: its card looks then, so its rows are
    there the first time Settings opens (it looked only once on screen)."""
    window.cfg.mic_device = 'Headset Mic (USB)'
    found = two_mics()
    monkeypatch.setattr(dm, 'mics', lambda names=(): [dict(m) for m in found])
    monkeypatch.setattr(dm, 'status', lambda mic=None: 'ready')
    card = RecoveryCard(window)
    assert not card.isVisible()
    wait(qapp, lambda: set(card.rows) == {GUID_A, GUID_B} and not card._checking)
    card.deleteLater()


def test_the_mic_in_use_without_the_effect_glows_its_install(window, qapp, monkeypatch):  # noqa: F811
    # a new mic or headset: the one in use has no mic effect yet, the other one does
    d, card = card_with(window, qapp, monkeypatch, two_mics('other', 'ready'))
    a, b = card.rows[GUID_A], card.rows[GUID_B]
    assert a.glow.button is a.buttons['install'] and a.glow.tone == 'warn'
    assert not hasattr(b, 'glow')
    # and the card says a new mic needs it too
    assert 'New mic or headset?' in card.new_mic.text()
    d.close()


def test_the_mic_in_use_is_listed_first(window, qapp, monkeypatch):  # noqa: F811
    found = two_mics('ready', 'other')
    found[0]['pa'], found[1]['pa'] = 'Desk Mic', 'Headset Mic (USB)'   # in use: the 2nd
    d, card = card_with(window, qapp, monkeypatch, found)
    first = card.list.itemAt(0).widget()
    assert first is card.rows[GUID_B] and first.name.text() == '#2 Headset Mic (USB)'
    d.close()


def _helper_box(d):
    card = d.findChild(RecoveryCard)
    return next(c for c in card.findChildren(QCheckBox)
                if c.text() == "Don't ask for admin each time")


def test_helper_switch_off_removes_it_and_on_brings_it_back(window, qapp, monkeypatch):  # noqa: F811
    from soundboard.mic import michelper as mh
    there, removed = [True], []
    monkeypatch.setattr(mh, 'installed', lambda: there[0])
    monkeypatch.setattr(mh, 'leftover', lambda: there[0])
    monkeypatch.setattr(dm, 'remove_helper', lambda: removed.append(1) or there.pop() and
                        there.append(False))
    monkeypatch.setattr(window.micctl, '_check_helper', lambda via='card': None)
    d = SettingsDialog(window, 'audio')
    box = _helper_box(d)
    assert window.cfg.mic_helper and box.isChecked()   # on by default: nothing changes
    box.click()
    wait(qapp, lambda: not window.micctl._helper_switching)
    assert removed == [1] and not window.cfg.mic_helper and not dm.helper_on
    assert not box.isChecked() and mh.will_ask()
    box.click()   # back on: no prompt now, the next set-up puts it back
    assert window.cfg.mic_helper and dm.helper_on and box.isChecked() and removed == [1]
    d.close()


def test_helper_switch_off_with_a_no_leaves_it_on(window, qapp, monkeypatch):  # noqa: F811
    from soundboard.mic import michelper as mh
    monkeypatch.setattr(mh, 'installed', lambda: True)
    monkeypatch.setattr(dm, 'remove_helper', lambda: None)   # No to Windows' prompt
    d = SettingsDialog(window, 'audio')
    box = _helper_box(d)
    box.click()
    wait(qapp, lambda: not window.micctl._helper_switching)
    assert window.cfg.mic_helper and dm.helper_on and box.isChecked()
    d.close()


def test_helper_switch_off_with_no_helper_asks_nothing(window, qapp, monkeypatch):  # noqa: F811
    from soundboard.mic import michelper as mh
    monkeypatch.setattr(mh, 'installed', lambda: False)
    monkeypatch.setattr(mh, 'leftover', lambda: False)
    monkeypatch.setattr(dm, 'remove_helper', lambda: pytest.fail("asked Windows"))
    d = SettingsDialog(window, 'audio')
    _helper_box(d).click()
    wait(qapp, lambda: not window.micctl._helper_switching)
    assert not window.cfg.mic_helper and not dm.helper_on
    d.close()
