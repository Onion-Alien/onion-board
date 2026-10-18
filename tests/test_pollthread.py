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
