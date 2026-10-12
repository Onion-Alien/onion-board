"""One download job, one bar that only goes forward (soundboard/jobprogress.py)."""
from soundboard.jobprogress import FETCHED, LOOKED_UP, JobProgress, batch


def _run(*payloads) -> list[float]:
    job = JobProgress()
    return [job.update(p) for p in payloads]


def _never_back(values):
    assert all(b >= a for a, b in zip(values, values[1:])), values


def test_look_up_download_and_convert_are_one_bar():
    got = _run("parsing", 0.0, 0.5, 1.0, "processing")
    _never_back(got)
    assert got[0] == 0.0
    assert got[1] == LOOKED_UP
    assert got[3] == FETCHED and got[4] == FETCHED   # converting: not "full" yet


def test_a_second_part_carries_on_from_where_the_first_stopped():
    """yt-dlp's video then its sound (or a retry): the bar doesn't start again."""
    got = _run("parsing", 0.3, 0.6, 0.0, 0.5, 1.0, "processing")
    _never_back(got)
    assert got[3] == got[2]            # the next part starts where it was
    assert got[5] == FETCHED


def test_a_retry_after_parsing_again_keeps_the_bar():
    got = _run("parsing", 0.8, "parsing", 0.1, -1)
    _never_back(got)
    assert got[-1] == FETCHED


def test_a_wobble_is_not_a_new_part():
    job = JobProgress()
    job.update(0.5)
    before = job.value
    job.update(0.45)   # an estimate went up a little: hold, don't rebase
    assert job.value == before
    job.update(1.0)
    assert job.value == FETCHED


def test_finish_is_full_and_late_updates_cant_move_it():
    job = JobProgress()
    job.update(0.4)
    assert job.finish() == 1.0
    for late in ("parsing", 0.1, "processing"):
        assert job.update(late) == 1.0
    job.reset()
    assert job.value == 0.0 and job.stage == "parsing"


def test_the_whole_list_is_one_bar():
    assert batch(0, None, 0) == 0.0
    assert batch(0, 0.5, 0) == 0.5
    # three picks: the first one done, the second half way: half of the list
    assert batch(1, 0.5, 1) == 0.5
    # the next pick starting doesn't drop the list's bar back
    assert batch(1, 1.0, 1) == batch(2, 0.0, 0)
    assert batch(3, None, 0) == 1.0
