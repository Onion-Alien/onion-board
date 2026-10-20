"""The search results' Play / Add and the download bar's queue, driven through the real
window the way a person clicks: cards picked while others load, ✕ on waiting rows,
Cancel, Stop all, Retry, a waiting row clicked to go next. The downloads are fakes the
test lands one by one (no network), so every order of events is checked: what plays,
what's added, and what the bar shows after each."""
import types

import numpy as np
import pytest

from soundboard.sounds.library import SoundMeta
from soundboard.ui.sounds import linkbar as linkbar_mod
from soundboard.ui.sounds.linkbar import PLAY_ID
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
        self.asked: list[tuple[str, dict]] = []    # (url, download_audio's options)
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
            net.asked.append((url, kw))
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
        self.now: dict[str, tuple[float, bool]] = {}   # what the fake engine plays
        monkeypatch.setattr(w.engine, "play", lambda sid, data, gain, **kw:
                            net.plays.append((sid, len(data))) or
                            net.now.__setitem__(sid, (0.0, False)) or object())
        monkeypatch.setattr(w.engine, "playing", lambda: dict(net.now))
        monkeypatch.setattr(w.engine, "stop", lambda sid, *a, **kw: net.now.pop(sid, None))
        monkeypatch.setattr(w, "_save_now", lambda: None)
        w.linkbar.done.connect(lambda *a: self.done.append(a))

    # what a person does
    def click(self, url: str, play: bool):
        r = types.SimpleNamespace(url=url, title=NAMES[url], seconds=90.0)
        self.w.searchctl._from_youtube(r, play)
        self.settle()

    def land(self, url: str):
        """The oldest download of `url` finishes (or fails, if it's in `fail`)."""
        i = next(i for i, (u, _r) in enumerate(self.jobs) if u == url)
        _u, run = self.jobs.pop(i)
        run()
        self.settle()

    def end(self):
        """The search song playing comes to its end; the window's next tick sees it."""
        self.now.pop(PLAY_ID, None)
        self.w.tickctl.tick()

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
    assert net.w.searchctl._link_url == A and net.w.searchctl._link_meta.name == "Shrek"
    assert not net.bar().shown   # it plays and nothing else is listed: the card goes
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


def test_plays_clicked_while_one_loads_all_play_in_order_never_cut_off(net):
    """The reported bug: Play on three cards, the third cancelled, and the second's
    download landed while the first played and cut it off. Every Play now plays, one
    after another, in the order clicked: one landing while another plays waits."""
    net.click(A, play=True)
    net.click(B, play=True)
    net.click(C, play=True)
    assert net.bar().waiting == [B, C]                # in the order clicked
    net.w.download_bar.cancel_requested.emit(C)       # its ✕
    net.land(A)
    assert net.played() == [480]
    net.land(B)
    assert net.played() == [480] and net.w.searchctl._link_url == A   # A keeps playing
    assert net.w.linkbar.up_next() == ["Random"]
    assert (B, "play", True) in net.done
    net.end()                                         # A ends: B starts
    assert net.played() == [480, 960] and net.w.searchctl._link_url == B
    assert net.w.linkbar.up_next() == []
    net.end()
    assert net.played() == [480, 960] and not net.jobs


def test_up_next_chips_play_now_or_come_out_and_stop_all_clears_them(net):
    for u in (A, B, C, D):
        net.click(u, play=True)
    for u in (A, B, C, D):
        net.land(u)
    assert net.played() == [480]
    assert net.w.linkbar.up_next() == ["Random", "Third", "Fourth"]
    shown = tuple(net.w.linkbar.up_next())
    assert not net.w.playing_row.isHidden() and net.w._chip_ids[2] == shown
    row, flow = net.w.playing_row, net.w._chips_hl
    assert flow.itemAt(0).widget().text() == "Now playing"     # first, then Up next
    chip = net.w._up_next_chip                       # one chip: how many wait
    assert chip.count.text() == "3"
    row.resize(330, row.height())                     # narrow: it stays, the row wraps
    assert not chip.isHidden()
    net.w.linkbar.drop_up_next(0, shown)              # Random's ✕
    net.w.linkbar.drop_up_next(0, shown)              # a double click: out of date
    assert net.w.linkbar.up_next() == ["Third", "Fourth"]
    net.w.linkbar.play_next(1, ("Third", "Fourth"))   # Fourth's chip: plays now
    assert net.played() == [480, 1920] and net.w.searchctl._link_url == D
    net.w.playctl.stop_all()
    assert net.w.linkbar.up_next() == []
    net.end()
    assert net.played() == [480, 1920]


def test_a_play_while_nothing_plays_starts_at_once(net):
    net.click(A, play=True)
    net.land(A)
    net.end()                                         # it ended: the player is free
    net.click(B, play=True)
    net.land(B)
    assert net.played() == [480, 960] and net.w.linkbar.up_next() == []


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


def test_a_full_queue_refuses_more_and_cancel_starts_the_next(net, monkeypatch):
    monkeypatch.setattr(linkbar_mod, "MAX_QUEUED", 3)
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


def test_add_and_play_on_one_card_then_another_card_keeps_both(net):
    """Add and Play on one card while it downloads, then a click on another card: the
    Play used to be dropped, and dropping it told the bar the running download had
    stopped, so the bar went blank while the Add was still downloading."""
    net.click(A, play=False)
    net.click(A, play=True)    # waits for A's download: no second one
    net.click(B, play=False)   # another card: A's Play must stand
    assert net.bar().shown and net.bar().url == A and net.bar().waiting == [B]
    assert len(net.jobs) == 1
    net.land(A)
    assert net.added == ["Shrek"] and net.played() == [480]   # added, then played
    assert net.bar().url == B and len(net.jobs) == 1          # B's turn, A not fetched twice
    net.land(B)
    assert net.added == ["Shrek", "Random"]
    assert not net.w.ytresults._fetching   # every card's button came back


def test_a_play_that_waits_its_turn_says_up_next_until_it_plays(net):
    """The reported confusion: a Play landing while a song plays went to Up next, but
    the bar said Playing, so it looked like nothing played. It says Up next (and stays
    up) till its turn, lists the others waiting, and their ✕ takes them out."""
    net.click(A, play=True)
    net.land(A)
    net.click(B, play=True)
    net.land(B)
    assert net.played() == [480] and net.w.linkbar.up_next() == ["Random"]
    bar = net.w.download_bar
    assert net.bar().url == B and net.bar().head == "Up next"
    assert net.bar().status == "Up next" and not bar._auto_hide.isActive()
    net.click(C, play=True)
    net.land(C)
    assert net.bar().url == C and net.bar().head == "Up next"
    assert [u for _t, u in bar._up_next] == [B, C]
    assert net.bar().status == "Up next · 1 before it"   # (B's row is listed under it)
    bar.up_next_drop.emit(B)                          # B's row ✕
    assert net.w.linkbar.up_next() == ["Third"]
    net.end()                                         # A ends: C, the bar's own, plays
    assert net.played() == [480, 1440]
    assert not net.bar().shown   # it plays and nothing else waits: the card goes


def test_now_playing_and_up_next_show_on_every_tab(net):
    """Played from Community (or any tab) while a song plays: the Now playing / Up
    next row shows there too, not only on the Sounds tab."""
    w = net.w
    w.show()
    w.tabs.setCurrentWidget(w.store)
    net.click(A, play=True)
    net.land(A)
    net.click(B, play=True)
    net.land(B)
    w.playctl._update_chips(w.engine.playing())
    assert w.playing_row.isVisible() and w._up_next_chip is not None
    assert not w.sounds_page.isAncestorOf(w.playing_row)


def test_play_skips_the_picture_add_keeps_it(net):
    """Play once has no pad to show a picture on, and fetching it was most of the
    wait (yt-dlp tries sizes YouTube doesn't have, seconds each). Add still gets it."""
    net.click(A, play=True)
    net.land(A)
    net.click(B, play=False)
    net.land(B)
    assert net.asked == [(A, {"progress": net.asked[0][1]["progress"], "auto_update": False,
                              "thumbnail": False}),
                         (B, {"progress": net.asked[1][1]["progress"], "auto_update": False})]


def test_add_after_play_takes_the_cards_picture(net, monkeypatch):
    """Add after Play reuses Play's download, which has no picture: the search card's
    picture goes on the pad instead."""
    from PySide6.QtGui import QPixmap
    pm = QPixmap(16, 9)
    stored = []
    monkeypatch.setattr(linkbar_mod.thumbs, "store",
                        lambda img, sid: stored.append((img.size().toTuple(), sid)) or "p.jpg")
    monkeypatch.setattr(net.w.linkbar, "picture_for", lambda url: pm if url == A else None)
    net.click(A, play=True)
    net.land(A)
    net.click(A, play=False)
    net.land(A)
    assert [u for u, _kw in net.asked] == [A]   # Play's file, not a second download
    meta = next(m for m in net.w.cfg.sounds if m.name == "Shrek")
    assert meta.image == "p.jpg" and stored == [((16, 9), meta.id)]


def _pad(net, url, monkeypatch, **how):
    """`url` added as a pad (its audio loaded), with `how` (mode, loop) set."""
    net.click(url, play=False)
    net.land(url)
    m = next(m for m in net.w.cfg.sounds if m.name == NAMES[url])
    for k, v in how.items():
        setattr(m, k, v)
    net.w.audio[m.id] = np.zeros((480, 2), np.int16)
    monkeypatch.setattr(net.w.searchctl, "_pad_for_link", lambda link: None)
    return m.id


def test_a_pad_stops_the_search_song_instead_of_playing_over_it(net, monkeypatch):
    """The reported double play: a pad (or the download bar's ▶ on an added one) set
    to stop the others left the search's song playing under it."""
    sid = _pad(net, C, monkeypatch)
    net.click(A, play=True)
    net.land(A)
    assert PLAY_ID in net.now
    net.w.playctl.play(sid)
    assert sid in net.now and PLAY_ID not in net.now


def test_overlap_and_loop_pads_still_play_over_the_search_song(net, monkeypatch):
    over = _pad(net, C, monkeypatch, mode="overlap")
    rain = _pad(net, D, monkeypatch, loop=True)
    net.click(A, play=True)
    net.land(A)
    net.w.playctl.play(over)
    net.w.playctl.play(rain)
    assert {over, rain, PLAY_ID} <= set(net.now)


def test_up_next_name_click_makes_way_for_it(net, monkeypatch):
    """A song's name in Up next plays it now like its ▶: the board's song playing
    stops, they never play together."""
    sid = _pad(net, C, monkeypatch)
    net.w.playctl.play(sid)
    net.click(A, play=True)
    net.land(A)
    assert net.w.linkbar.up_next() == ["Shrek"]   # waits for the pad's song
    item = net.w.playctl._up_next_items()[0]
    item.on_click()
    assert PLAY_ID in net.now and sid not in net.now
