"""The download banner's running row: Bun always, then the sound's picture beside him,
and the tick / ✗ flash lands on Bun, not on the picture."""
from PySide6.QtGui import QColor, QPixmap

from conftest import process_events
from soundboard.ui.downloadbar import DownloadBar


def _bar(qapp):
    bar = DownloadBar()
    bar.resize(1000, 200)
    bar.show()
    process_events(qapp, lambda: False, 0.05)
    return bar


def _pic():
    pm = QPixmap(320, 180)
    pm.fill(QColor("#c03030"))
    return pm


def test_bun_comes_first_and_the_picture_sits_beside_him(qapp):
    bar = _bar(qapp)
    for pm in (_pic(), None):            # a video with a picture, an MP3 without one
        bar.set_active(f"https://example.com/{pm is None}", "A song", "add", pm)
        process_events(qapp, lambda: False, 0.05)
        assert bar.scribe.isVisibleTo(bar) and bar.thumb.isVisibleTo(bar)
        assert not bar.thumb.pixmap().isNull()          # the placeholder when there's none
        assert (bar._scribe_box.mapTo(bar, bar._scribe_box.rect().topLeft()).x()
                < bar.thumb.mapTo(bar, bar.thumb.rect().topLeft()).x())
    bar.close()


def test_the_outcome_flash_lands_on_bun(qapp):
    bar = _bar(qapp)
    bar.set_active("https://example.com/v", "A song", "add", _pic())
    process_events(qapp, lambda: False, 0.05)
    bar.set_failed("https://example.com/v", "add")
    bar.set_done("https://example.com/v", "add", False)
    left = bar.scribe.mapTo(bar, bar.scribe.rect().topLeft()).x()
    assert bar.outcome.spot.isValid() and round(bar.outcome.spot.x()) == left
    bar.close()


def test_a_narrow_banner_drops_both(qapp):
    bar = _bar(qapp)
    bar.set_active("https://example.com/v", "A song", "add", _pic())
    bar.resize(500, 200)
    process_events(qapp, lambda: False, 0.05)
    assert not bar.scribe.isVisibleTo(bar) and not bar.thumb.isVisibleTo(bar)
    bar.close()


def test_one_pick_hands_over_to_the_next_without_a_jump(qapp):
    """A queue: when one ends and the next starts, Bun stays (no running off), and the
    title, Bun, the picture and the summary bar keep their places."""
    bar = _bar(qapp)
    urls = ["https://example.com/1", "https://example.com/2", "https://example.com/3"]

    def spots():
        def at(w):
            return w.mapTo(bar, w.rect().topLeft()) if w.isVisibleTo(bar) else None
        return [at(bar.scribe), at(bar.thumb), at(bar.lbl_title).y(), at(bar.s_bar)]
    seen = []
    for i, url in enumerate(urls):
        bar.set_queue([{"url": u, "title": "Next", "kind": "add"} for u in urls[i + 1:]])
        bar.set_active(url, "A song", "add", _pic())
        bar.set_progress(url, 0.5)
        process_events(qapp, lambda: False, 0.05)
        seen.append(spots())
        bar.set_done(url, "add", True)
        process_events(qapp, lambda: False, 0.05)
        if i < len(urls) - 1:   # ended, the next one waiting
            assert bar.s_bar.isVisibleTo(bar) and bar.scribe.isVisibleTo(bar)
            assert spots()[:3] == seen[-1][:3]
        process_events(qapp, lambda: not bar._held, 3)   # the flash, then the next
    assert all(s == seen[0] for s in seen)
    bar.close()
