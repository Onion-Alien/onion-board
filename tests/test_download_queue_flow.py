"""The search results' Play / Add and the download bar's queue, driven through the real
window the way a person clicks: cards picked while others load, ✕ on waiting rows,
Cancel, Stop all, Retry, a waiting row clicked to go next. The downloads are fakes the
test lands one by one (no network), so every order of events is checked: what plays,
what's added, and what the bar shows after each."""
import types

import numpy as np
import pytest

from soundboard.library import SoundMeta
from soundboard.ui import linkbar as linkbar_mod
from soundboard.ui.linkbar import PLAY_ID
from test_mainwindow import window as main_window  # noqa: F401  (the real MainWindow)

A = "https://www.youtube.com/watch?v=aaaaaaaaaaa"
B = "https://www.youtube.com/watch?v=bbbbbbbbbbb"
C = "https://www.youtube.com/watch?v=ccccccccccc"
D = "https://www.youtube.com/watch?v=ddddddddddd"
E = "https://www.youtube.com/watch?v=eeeeeeeeeee"
NAMES = {A: "Shrek", B: "Random", C: "Third", D: "Fourth", E: "One too many"}


class Net:
    """Fake downloads: each one waits until the test lands it (or makes it fail)."""

    def __init__(self, w, monkeypatch):
        self.w = w
        self.jobs: list[tuple[str, object]] = []   # (url, run) started, not landed yet
        self.fail: set[str] = set()
        self.plays: list[tuple[str, int]] = []      # (sid, frames) the engine was asked
        self.added: list[str] = []                  # names added to the library
        self.done: list[tuple[str, str, bool]] = []
        net = self

        class Worker:
            def __init__(self, target, args, **kw):
                net.jobs.append((args[1], lambda: target(*args)))

            def start(self):
                pass

        fake = types.SimpleNamespace(**{k: getattr(linkbar_mod.threading, k)
                                        for k in dir(linkbar_mod.threading)
                                        if not k.startswith("__")})
        fake.Thread = Worker
        monkeypatch.setattr(linkbar_mod, "threading", fake)

        def download(url, **kw):
            if url in net.fail:
                raise RuntimeError("the site said no")
            return f"C:/nowhere/{url[-3:]}.m4a", NAMES[url]
        frames = {A: 480, B: 960, C: 1440, D: 1920}
        monkeypatch.setattr(linkbar_mod.ytdl, "download_audio", download)
        monkeypatch.setattr(linkbar_mod, "_drop_temp", lambda path: None)
        by_path = {f"C:/nowhere/{u[-3:]}.m4a": n for u, n in frames.items()}
        monkeypatch.setattr(linkbar_mod, "decode_int16", lambda path: (
            np.zeros((by_path[str(path)], 2), np.int16), 1.0))
        monkeypatch.setattr(linkbar_mod, "fingerprint", lambda path: path)
        ids = iter(range(100))

        def import_file(path, color, name="", **kw):
            meta = SoundMeta(id=f"dl{next(ids)}", name=name, file=path, duration=1.0)
            net.added.append(name)
            return meta, np.zeros((480, 2), np.int16)
        monkeypatch.setattr(linkbar_mod, "import_file", import_file)
        monkeypatch.setattr(linkbar_mod.thumbs, "find_in", lambda folder: None)
        monkeypatch.setattr(w.engine, "prepare", lambda *a, **kw: None)
        monkeypatch.setattr(w.engine, "play", lambda sid, data, gain, **kw:
                            net.plays.append((sid, len(data))) or object())
        monkeypatch.setattr(w, "_save_now", lambda: None)
        w.linkbar.done.connect(lambda *a: self.done.append(a))

    # what a person does
    def click(self, url: str, play: bool):
        r = types.SimpleNamespace(url=url, title=NAMES[url], seconds=90.0)
        self.w._from_youtube(r, play)
        self.settle()

    def land(self, url: str):
        """The oldest download of `url` finishes (or fails, if it's in `fail`)."""
        i = next(i for i, (u, _r) in enumerate(self.jobs) if u == url)
        _u, run = self.jobs.pop(i)
        run()
        self.settle()

    def settle(self):
        """The banner's tick / red flash is over: what waited for it plays out."""
        for bar in (self.w.download_bar, self.w.mini_download_bar):
            while bar._held is not None:
                bar._hold.stop()
                bar._release()

    # what we look at
    def played(self) -> list[int]:
        """The lengths of the Play onces that reached the engine (frames tell them apart)."""
        return [n for sid, n in self.plays if sid == PLAY_ID]

    def bar(self):
        b = self.w.download_bar
        return types.SimpleNamespace(
            url=b.url, stage=b.stage, shown=not b.isHidden(),
            waiting=[q["url"] for q in b._queue], failed=[f["url"] for f in b._failed],
            head=b.h_text.text(), status=b.lbl_status.text())


@pytest.fixture
def net(main_window, monkeypatch):  # noqa: F811
    return Net(main_window, monkeypatch)


def test_play_then_queue_and_remove_another_still_plays(net):
    """The reported bug: Play on one card, Add on another while it loads, ✕ on that
    waiting one: the first must still play, and the bar must say so."""
    net.click(A, play=True)
    net.click(B, play=False)
    assert net.bar().waiting == [B]
    net.w.download_bar.cancel_requested.emit(B)   # its ✕
    assert net.bar().waiting == [] and net.bar().url == A
    net.land(A)
    assert net.played() == [480]
    assert net.w._link_url == A and net.w._link_meta.name == "Shrek"
    assert net.bar().stage == "done" and net.bar().shown and "Playing" in net.bar().head
    assert (A, "play", True) in net.done


def test_play_then_add_another_plays_then_adds_it(net):
    net.click(A, play=True)
    net.click(B, play=False)
    net.land(A)
    assert net.played() == [480]
    assert net.bar().url == B and net.bar().stage == "parsing"   # B started on its own
    net.land(B)
    assert net.added == ["Random"] and "Added" in net.bar().head
    assert not net.jobs


def test_a_second_play_replaces_the_first_and_the_first_never_plays(net):
    net.click(A, play=True)
    net.click(B, play=True)
    net.land(A)    # the old one lands late
    net.land(B)
    assert net.played() == [960]
    assert net.w._link_url == B


def test_play_on_the_card_already_loading_doesnt_start_it_again(net):
    net.click(A, play=True)
    net.click(B, play=False)
    net.click(A, play=True)    # impatient second click
    assert len(net.jobs) == 1
    net.land(A)
    assert net.played() == [480] and net.bar().url == B


def test_play_goes_before_waiting_adds(net):
    net.click(A, play=False)
    net.click(B, play=False)
    net.click(C, play=True)
    assert net.bar().waiting == [C, B]
    net.land(A)
    assert net.bar().url == C
    net.land(C)
    assert net.played() == [1440] and net.bar().url == B
    net.land(B)
    assert net.added == ["Shrek", "Random"]


def test_a_full_queue_refuses_more_and_cancel_starts_the_next(net):
    net.click(A, play=False)
    for u in (B, C, D):
        net.click(u, play=False)
    assert net.bar().waiting == [B, C, D]
    net.click(E, play=False)                       # refused with a toast, nothing breaks
    assert net.bar().waiting == [B, C, D] and len(net.jobs) == 1
    net.w.download_bar._on_cancel()   # the running row's ✕
    assert net.bar().url == B and net.bar().waiting == [C, D]
    net.land(A)    # the cancelled one lands late: not added
    assert net.added == []
    net.land(B)
    assert net.added == ["Random"] and net.bar().url == C


def test_a_failed_one_shows_retry_and_the_queue_moves_on(net):
    net.fail.add(A)
    net.click(A, play=False)
    net.click(B, play=False)
    net.land(A)
    assert net.bar().failed == [A] and net.bar().url == B
    net.fail.clear()
    net.w.download_bar._retry(A)
    assert net.bar().waiting == [A] and net.bar().failed == []
    net.land(B)
    net.land(A)
    assert net.added == ["Random", "Shrek"]


def test_a_failed_play_says_so_even_with_another_card_showing(net):
    net.fail.add(A)
    net.click(A, play=True)
    net.click(B, play=False)
    net.land(A)
    assert net.played() == [] and net.bar().failed == [A]
    assert (A, "play", False) in net.done and net.bar().url == B


def test_a_waiting_row_clicked_goes_next(net):
    net.click(A, play=False)
    net.click(B, play=False)
    net.click(C, play=False)
    net.w.download_bar.front_requested.emit(C)
    assert net.bar().waiting == [C, B]
    net.land(A)
    assert net.bar().url == C


def test_stop_all_drops_everything_and_late_landings_do_nothing(net):
    net.click(A, play=True)
    net.click(B, play=False)
    net.click(C, play=False)
    net.w.download_bar._on_stop_all()
    assert not net.bar().shown and not net.w.linkbar.downloading()
    net.land(A)
    assert net.played() == [] and net.added == [] and not net.bar().shown
    assert len(net.jobs) == 0


def test_add_and_play_on_one_card_share_its_download(net):
    net.click(A, play=False)
    net.click(A, play=True)
    assert len(net.jobs) == 1
    net.land(A)
    assert net.added == ["Shrek"] and net.played() == [480] and not net.jobs
