"""A pasted link that can never work (copy-protected, gone) shows the reason alone: no
Try again, no "close the app" advice, no Report. One that may work next time keeps them."""
from conftest import process_events

from soundboard.online import ytdl
from soundboard.ui.sounds.ytsearch import SearchResults

URL = "https://soundcloud.com/someone/a-track"


def pasted(qapp, monkeypatch, raw: str) -> SearchResults:
    def lookup_all(url, direct=False):
        raise ytdl._readable(ytdl.DownloadError(raw))
    monkeypatch.setattr(ytdl, "lookup_all", lookup_all)
    panel = SearchResults()
    panel.show_link(URL)
    assert process_events(qapp, lambda: panel.failed)
    return panel


def test_a_copy_protected_link_offers_nothing_to_press(qapp, monkeypatch):
    panel = pasted(qapp, monkeypatch, "ERROR: [soundcloud] 1: This video is DRM protected")
    card = panel.oops
    assert "copy-protected" in card.line.text()
    assert card.btn_retry.isHidden() and card.btn_report.isHidden() and card.what.isHidden()


def test_a_link_that_is_gone_offers_nothing_to_press(qapp, monkeypatch):
    panel = pasted(qapp, monkeypatch, "ERROR: [youtube] abc: Video unavailable")
    card = panel.oops
    assert card.btn_retry.isHidden() and card.btn_report.isHidden() and card.what.isHidden()


def test_a_link_that_timed_out_can_still_be_tried_again(qapp, monkeypatch):
    panel = pasted(qapp, monkeypatch, "ERROR: unable to download: The read operation timed out")
    card = panel.oops
    assert not card.btn_retry.isHidden() and not card.what.isHidden()
