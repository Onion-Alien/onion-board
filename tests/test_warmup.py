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
