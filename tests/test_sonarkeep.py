"""SteelSeries Sonar's devices kept while the app's mic is Sonar's (soundboard.mic.
sonarkeep): noted while the mic is fine, set back after an audio restart moved them."""
from soundboard.mic import directmic as dm
from soundboard.mic import sonarkeep as sk
from test_directmic import BEFORE, SPEAKERS, _FakeSonar, _sonar_kit
from test_mainwindow import window  # noqa: F401 - the real window, offscreen

MOVED = {**BEFORE, "mic": ("{0.0.1.00000000}.{99999999-9999-9999-9999-999999999999}", True),
         "game": (SPEAKERS, True)}


def routes(channels: dict) -> dict:
    """{channel: (device, running)} as Sonar's look-up gives it: keyed by (list, channel)."""
    return {("classicRedirections", c): v for c, v in channels.items()}


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def wait(self, s):
        self.t += s


def keep(states, set_back=None):
    states = [routes(st) for st in states]
    calls = []

    def devices():
        return states.pop(0) if len(states) > 1 else states[0]

    def back(saved):
        calls.append(saved)
        return True if set_back is None else set_back
    return sk.SonarKeep(devices, back), calls


def test_noted_while_the_mic_is_fine_and_on_sonar_only():
    k, _ = keep([BEFORE])
    assert k.tick(0.0, on_sonar=False, mic_ok=True) is None
    assert k.tick(1.0, on_sonar=True, mic_ok=True) == "note"
    k.note(1.0)
    assert k.saved == routes(BEFORE) and not k.busy
    assert k.tick(2.0, True, True) is None                 # not again before NOTE_S
    assert k.tick(1.0 + sk.NOTE_S, True, True) == "note"
    k.note(31.0)
    assert k.tick(40.0, on_sonar=False, mic_ok=True) is None
    assert k.saved is None                                  # another mic: forgotten


def test_an_audio_restart_gets_sonars_devices_set_back():
    """The mic drops out and comes back (Windows' audio restarted): Sonar moved its mic
    to another device and saved it, so they're set back to what was noted before."""
    k, calls = keep([BEFORE, MOVED])
    clock = Clock()
    assert k.tick(clock(), True, True) == "note"
    k.note(clock())
    for _ in range(3):   # the restart: the mic gone for a few seconds
        clock.wait(1)
        assert k.tick(clock(), True, False) is None
    clock.wait(1)
    assert k.tick(clock(), True, True) == "back"
    assert k.back(clock.wait, clock) is True
    assert calls == [routes(BEFORE)] and not k.busy


def test_nothing_is_set_when_sonar_kept_its_devices():
    k, calls = keep([BEFORE])
    clock = Clock()
    k.tick(clock(), True, True)
    k.note(clock())
    clock.wait(2)
    k.tick(clock(), True, False)
    clock.wait(1)
    assert k.tick(clock(), True, True) == "back"
    assert k.back(clock.wait, clock) is None
    assert calls == []                                      # watched CHECK_S, left alone
    assert clock() >= 1003 + sk.CHECK_S


def test_a_mic_back_long_after_isnt_an_audio_restart():
    """Out for longer than BACK_WITHIN_S (unplugged, the PC asleep): what Sonar has then
    may be the user's own choice, so it's left as it is."""
    k, calls = keep([BEFORE, MOVED])
    k.tick(0.0, True, True)
    k.note(0.0)
    k.tick(1.0, True, False)
    assert k.tick(2.0 + sk.BACK_WITHIN_S, True, True) is None
    assert calls == []


def test_a_note_taken_after_the_mic_dropped_is_never_what_goes_back():
    k, calls = keep([MOVED])
    k.tick(0.0, True, True)        # the note is due, but the worker gets to it late...
    k.tick(1.0, True, False)       # ...after the mic dropped (Sonar mid-restart)
    k.note(1.5)
    assert k.tick(3.0, True, True) is None
    assert calls == []


def test_through_sonars_own_server(monkeypatch, tmp_path):
    """The real look-up and set-back (directmic.sonar_devices / sonar_set_back) against a
    Sonar that moved its mic and game channel: both set back through its server."""
    sonar = _FakeSonar([BEFORE, BEFORE, MOVED])
    _sonar_kit(monkeypatch, tmp_path, sonar)
    k = sk.SonarKeep(dm.sonar_devices, dm.sonar_set_back)
    k.tick(0.0, True, True)
    k.note(0.0)
    assert k.saved == routes(BEFORE)
    k.tick(1.0, True, False)
    assert k.tick(2.0, True, True) == "back"
    assert k.back(dm.time.sleep, dm.time.monotonic) is True
    assert f"/classicRedirections/mic/deviceId/{BEFORE['mic'][0]}" in sonar.puts
    assert f"/classicRedirections/game/deviceId/{BEFORE['game'][0]}" in sonar.puts


def test_the_window_keeps_sonar_while_its_mic_is_sonars(window, monkeypatch):  # noqa: F811
    """Once a second the window asks; the work runs on its own thread (here at once)."""
    mc = window.micctl
    monkeypatch.setattr(mc.sonar_poll, "run", lambda fn: fn())
    k, calls = keep([BEFORE, MOVED])
    monkeypatch.setattr(mc, "sonar", k)
    live = [True]
    monkeypatch.setattr(window.engine, "mic_live", lambda: live[0])
    window.cfg.mic_device = "Microphone (Realtek(R) Audio)"
    mc.keep_sonar()
    assert k.saved is None                                  # not Sonar's mic: nothing
    window.cfg.mic_device = "SteelSeries Sonar - Microphone (SteelSeries Sonar Virtual Audio)"
    mc.keep_sonar()
    assert k.saved == routes(BEFORE)
    live[0] = False
    mc.keep_sonar()
    live[0] = True
    mc.keep_sonar()
    assert calls == [routes(BEFORE)]
