"""The audio warm-up (soundboard/audio/warmup.py) runs every first-use path once at
start-up, so the first live toggle doesn't stutter."""
import threading

from soundboard.audio import warmup


def test_warm_runs_every_path_without_error():
    # drives the live effects, the pitch shifter and a resampler; raises if any path
    # is wired up wrong (a wrong knob key, a shape mismatch)
    warmup._warm()


def test_warm_up_runs_on_a_daemon_thread_once():
    warmup._started = False
    warmup.warm_up()
    warmup.warm_up()   # second call is a no-op: it never starts a second thread
    threads = [t for t in threading.enumerate() if t.name == "audio-warmup"]
    assert len(threads) <= 1
    for t in threads:
        assert t.daemon
        t.join(timeout=5)
        assert not t.is_alive()


def test_warm_voices_runs_every_maths_voice_on_its_own_chain(monkeypatch):
    # every built-in voice's maths effects go through a throwaway chain: never the
    # engine's, and never one that loads sound files (those start threads)
    from soundboard import voicefx

    seen: list[set[str]] = []
    real = voicefx.VoiceChain.configure

    def spy(self, spec):
        seen.append(set(spec["effects"]))
        return real(self, spec)

    monkeypatch.setattr(voicefx.VoiceChain, "configure", spy)
    before = {t.name for t in threading.enumerate()}
    warmup._warm_voices()
    on = set().union(*seen)
    assert {"pitch", "robot", "chorus", "growl", "ringmod", "tone", "helmet", "radio",
            "wobble", "polish"} <= on
    assert not on & {"cat", "dog", "chatter", "drums"}
    started = {t.name for t in threading.enumerate()} - before
    assert not [n for n in started if n.startswith("voice-calls")]
