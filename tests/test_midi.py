"""MIDI pad controllers as hotkeys (soundboard.midi): the combo format, decoding the
messages, which devices get opened, and pads firing / releasing hotkeys. A fake
winmm backend stands in for real devices."""
from soundboard import midi, winkeys
from soundboard.settings import HotkeyDialog, pretty_key


class FakeWinMM:
    def __init__(self, names=(), busy=()):
        self.names = list(names)
        self.busy = set(busy)
        self.opened: dict[int, str] = {}   # key -> name
        self.on_message = self.on_closed = lambda *_: None

    def devices(self):
        return list(self.names)

    def open(self, index, key):
        name = self.names[index]
        if name in self.busy:
            raise midi.Busy(4, "busy")
        self.opened[key] = name
        return key

    def close(self, handle):
        self.opened.pop(handle, None)

    def hit(self, name, msg):
        """A message from the device called `name` (as winmm would send it)."""
        for key, n in list(self.opened.items()):
            if n == name:
                self.on_message(key, msg)


def note_on(n, vel=100, ch=0):
    return 0x90 | ch | n << 8 | vel << 16


def listen(m):
    got = []
    m.pressed.connect(lambda c: got.append(("press", c)))
    m.released.connect(lambda c: got.append(("release", c)))
    return got


def test_combo_format_round_trips_and_reads_nicely():
    c = midi.make("note", 36, "LPD8")
    assert c == "midi:note 36:LPD8" and midi.is_midi(c)
    assert midi.parse(c) == ("note", 36, "LPD8")
    assert midi.parse("midi:cc 20:MPD218 Port A") == ("cc", 20, "MPD218 Port A")
    assert midi.parse("midi:note 36:Dev:with:colons") == ("note", 36, "Dev:with:colons")
    for bad in ("ctrl+s", "midi:", "midi:note x:LPD8", "midi:bend 3:LPD8", "midi:note 3:"):
        assert midi.parse(bad) is None
    assert pretty_key(c) == "LPD8 note 36"
    assert midi.pretty("midi:pc 3:X") == "X program 3"
    assert midi.short(c) == "♪36" and midi.short("midi:cc 7:X") == "CC7"
    assert not winkeys.parse(c)   # never mistaken for a key combo


def test_decoding_notes_control_changes_and_program_changes():
    assert midi.decode(note_on(36)) == ("press", "note", 36)
    assert midi.decode(note_on(36, ch=9)) == ("press", "note", 36)   # any channel
    assert midi.decode(note_on(36, vel=0)) == ("release", "note", 36)
    assert midi.decode(0x80 | 36 << 8) == ("release", "note", 36)
    assert midi.decode(0xB0 | 20 << 8 | 127 << 16) == ("press", "cc", 20)
    assert midi.decode(0xB0 | 20 << 8) == ("release", "cc", 20)
    assert midi.decode(0xC0 | 5 << 8) == ("press", "pc", 5)
    assert midi.decode(0xF8) is None            # clock
    assert midi.decode(0xD0 | 40 << 8) is None  # aftertouch


def test_only_the_devices_hotkeys_use_are_opened(qapp):
    fake = FakeWinMM(["LPD8", "Keystation 49"])
    m = midi.MidiIn(fake)
    assert fake.opened == {}                    # nothing wanted: nothing held open
    m.want({"LPD8"})
    assert list(fake.opened.values()) == ["LPD8"]   # the keyboard stays free for a DAW
    m.capture(True)                             # the hotkey dialog listens to every one
    assert sorted(fake.opened.values()) == ["Keystation 49", "LPD8"]
    m.capture(False)
    assert list(fake.opened.values()) == ["LPD8"]
    m.want(set())
    assert fake.opened == {} and not m._timer.isActive()


def test_pads_press_and_release(qapp):
    fake = FakeWinMM(["LPD8"])
    m = midi.MidiIn(fake)
    got = listen(m)
    m.want({"LPD8"})
    fake.hit("LPD8", note_on(36))
    fake.hit("LPD8", note_on(36, vel=0))
    fake.hit("LPD8", 0xF8)                      # ignored
    assert got == [("press", "midi:note 36:LPD8"), ("release", "midi:note 36:LPD8")]


def test_a_held_cc_pad_fires_once(qapp):
    fake = FakeWinMM(["Pads"])
    m = midi.MidiIn(fake)
    got = listen(m)
    m.want({"Pads"})
    for v in (127, 100, 90, 0, 0, 127):         # pressure-sensitive pads repeat values
        fake.hit("Pads", 0xB0 | 20 << 8 | v << 16)
    assert [g[0] for g in got] == ["press", "release", "press"]


def test_a_device_another_program_has_is_reported_and_retried(qapp):
    fake = FakeWinMM(["LPD8"], busy={"LPD8"})
    m = midi.MidiIn(fake)
    seen = []
    m.busy_changed.connect(seen.append)
    m.want({"LPD8"})
    assert m.busy == ["LPD8"] and seen == [["LPD8"]] and fake.opened == {}
    assert m._timer.isActive()                  # looked for again
    fake.busy.clear()                           # the DAW closed
    m.sync()
    assert list(fake.opened.values()) == ["LPD8"] and m.busy == [] and seen[-1] == []


def test_unplugged_and_plugged_back_in(qapp):
    fake = FakeWinMM(["LPD8"])
    m = midi.MidiIn(fake)
    got = listen(m)
    m.want({"LPD8"})
    (key,) = fake.opened
    fake.on_closed(key)                         # winmm: the device went away
    fake.names = []
    m.sync()
    assert fake.opened == {}
    fake.names = ["LPD8"]
    m.sync()
    fake.hit("LPD8", note_on(40))
    assert got == [("press", "midi:note 40:LPD8")]


def test_closing_a_device_lets_go_of_the_pads_held_on_it(qapp):
    """Turned off (or no longer wanted) while a hold-to-play pad is down: no note-off
    will ever come, so closing it releases what was held."""
    fake = FakeWinMM(["LPD8"])
    m = midi.MidiIn(fake)
    got = listen(m)
    m.want({"LPD8"})
    fake.hit("LPD8", note_on(36))
    fake.hit("LPD8", note_on(37))
    fake.hit("LPD8", note_on(37, vel=0))
    fake.hit("LPD8", 0xC0 | 5 << 8)             # program change: nothing to release
    (key,) = fake.opened
    fake.on_closed(key)                         # switched off
    fake.names = []
    m.sync()
    assert got[-1] == ("release", "midi:note 36:LPD8")
    assert [g for g in got if g[0] == "release"] == [("release", "midi:note 37:LPD8"),
                                                     ("release", "midi:note 36:LPD8")]


def test_two_of_the_same_controller_are_told_apart(qapp):
    fake = FakeWinMM(["LPD8", "LPD8"])
    m = midi.MidiIn(fake)
    assert m.devices() == ["LPD8", "LPD8 (2)"]
    got = listen(m)
    m.want({"LPD8 (2)"})
    assert len(fake.opened) == 1
    (key,) = fake.opened
    fake.on_message(key, note_on(36))
    assert got == [("press", "midi:note 36:LPD8 (2)")]


def test_hotkeys_fire_and_release_actions_from_pads(qapp):
    fake = FakeWinMM(["LPD8"])
    hk = winkeys.Hotkeys(midi.MidiIn(fake))
    try:
        fired, released = [], []
        hk.fired.connect(fired.append)
        hk.released.connect(released.append)
        hk.register({"midi:note 36:LPD8": "sound1", "midi:note 37:Other": "sound2"})
        assert list(fake.opened.values()) == ["LPD8"]
        fake.hit("LPD8", note_on(36))
        fake.hit("LPD8", note_on(38))           # not a hotkey
        fake.hit("LPD8", note_on(36, vel=0))
        assert fired == ["sound1"] and released == ["sound1"]
        hk.pause()                              # the hotkey dialog: pads stop firing
        assert fake.opened == {}
    finally:
        hk.stop()


def test_the_hotkey_dialog_takes_a_pad_hit(qapp):
    fake = FakeWinMM(["LPD8"])
    hk = winkeys.Hotkeys(midi.MidiIn(fake))
    try:
        d = HotkeyDialog(hk)
        assert "LPD8" in d.pads_note.text()
        d.show()
        fake.hit("LPD8", note_on(36))
        assert d.result_combo == "midi:note 36:LPD8" and d.result() == d.DialogCode.Accepted
        assert fake.opened == {}                # listening stopped with the dialog

        d = HotkeyDialog(hk, pads=False)        # the push-to-talk key can't be a pad
        d.show()
        assert fake.opened == {} and d.pads_note.isHidden()
        d.reject()
    finally:
        hk.stop()


def test_the_hotkey_dialog_says_when_a_pad_is_busy(qapp):
    fake = FakeWinMM(["LPD8"], busy={"LPD8"})
    hk = winkeys.Hotkeys(midi.MidiIn(fake))
    try:
        d = HotkeyDialog(hk)
        assert "another program" in d.pads_note.text()
        d.reject()
    finally:
        hk.stop()
