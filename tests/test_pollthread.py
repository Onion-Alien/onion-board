"""pollthread: a timer's repeated look-up runs on one thread kept for it, never a new
thread each time (the UI thread waited in Thread.start: 2.0.4's freezes)."""
import threading

from soundboard.core.pollthread import PollThread


def test_every_job_runs_in_order_on_one_thread():
    poll, done, ran = PollThread("test-poll"), threading.Event(), []
    for i in range(5):
        poll.run(lambda i=i: ran.append((i, threading.current_thread())))
    poll.run(done.set)
    assert done.wait(5)
    assert [i for i, _t in ran] == [0, 1, 2, 3, 4]
    threads = {t for _i, t in ran}
    assert len(threads) == 1 and threading.main_thread() not in threads
    assert next(iter(threads)).name == "test-poll"
    poll.stop()


def test_a_failing_job_never_stops_the_next(caplog):
    poll, done = PollThread("test-poll"), threading.Event()
    poll.run(lambda: 1 / 0)
    poll.run(done.set)
    assert done.wait(5)
    assert "test-poll failed" in caplog.text
    poll.stop()


def test_once_stopped_its_thread_ends_and_new_jobs_are_dropped():
    poll, done, ran = PollThread("test-poll"), threading.Event(), []
    poll.run(done.set)
    assert done.wait(5)
    thread = poll._thread
    assert thread is not None
    poll.stop()
    thread.join(5)
    assert not thread.is_alive()
    poll.run(lambda: ran.append(1))
    assert poll._thread is thread and not ran


def test_the_first_start_never_waits_for_the_thread_to_get_going(monkeypatch):
    """A freeze report: the window stuck 30 s to 2 min in the device thread's first
    start, from a UI tick, on a PC short of memory. Thread.start waits with no limit
    for the new thread to run; the app's long-lived threads start without waiting."""
    import time

    from soundboard.audio import devicelist
    from soundboard.audio.engineparts import DeviceWorker

    def stuck(self):
        time.sleep(3)
        raise AssertionError("Thread.start was used")
    monkeypatch.setattr(threading.Thread, "start", stuck)
    ran, done = [], threading.Event()
    t0 = time.monotonic()
    poll = PollThread("test-poll")
    poll.run(lambda: ran.append("poll"))
    devices = DeviceWorker("test-devices")
    devices.run(lambda: ran.append("devices") or 1, lambda _r: done.set())
    answered, value = devicelist._Asker().ask(lambda: "list")
    assert time.monotonic() - t0 < 2
    assert answered and value == "list"
    assert done.wait(5) and "devices" in ran
    poll.stop()
    poll._thread.join(5)
    assert "poll" in ran and not poll._thread.is_alive()
