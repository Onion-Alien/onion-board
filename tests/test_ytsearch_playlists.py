"""YouTube search results' Videos / Playlists switch beside Back: playlists found by a
search open to their videos (Add all), and Back comes back to the playlists."""
from conftest import process_events

from soundboard.online import ytdl
from soundboard.ui.sounds.ytsearch import SearchResults

PL_URL = "https://www.youtube.com/playlist?list=PLabc"


def fake(monkeypatch):
    calls = []

    def search(query, count=20, source="youtube", direct=False, start=1, playlists=False):
        calls.append((query, source, playlists))
        if playlists:
            return [ytdl.Result("PLabc", "Road trip", "Band", 0.0, source=ytdl.PLAYLIST,
                                link=PL_URL)]
        return [ytdl.Result("vid00000001", "One song", "Band", 60.0)]
    monkeypatch.setattr(ytdl, "search", search)
    monkeypatch.setattr(ytdl, "lookup_all", lambda url, direct=False: ytdl.Playlist(
        "Road trip", [ytdl.Result(f"vid0000000{i}", f"Song {i}", "Band", 60.0)
                      for i in range(3)]))
    return calls


def test_the_switch_searches_youtube_playlists_and_back_to_videos(qapp, monkeypatch):
    calls = fake(monkeypatch)
    panel = SearchResults()
    panel.search("lofi")
    assert process_events(qapp, lambda: panel._rows)
    assert panel.kind_toggle.isVisibleTo(panel) and panel.kind_toggle.kind() == "videos"
    panel.kind_toggle.buttons["playlists"].click()
    assert process_events(qapp, lambda: panel._rows and panel._rows[0].playlist)
    row = panel._rows[0]
    assert row.btn_play.text() == "Open" and row.btn_add.text() == "Add all"
    assert row.sub.full == "Playlist · Band"
    panel.kind_toggle.buttons["playlists"].click()   # the one shown: not searched again
    panel.kind_toggle.buttons["videos"].click()
    assert process_events(qapp, lambda: panel._rows and not panel._rows[0].playlist)
    assert calls == [("lofi", "youtube", False), ("lofi", "youtube", True),
                     ("lofi", "youtube", False)]


def test_opening_a_found_playlist_shows_its_videos_and_back_returns(qapp, monkeypatch):
    calls = fake(monkeypatch)
    played = []
    panel = SearchResults()
    panel.play.connect(played.append)
    panel.kind_toggle.buttons["playlists"].setChecked(True)
    panel.search("lofi")
    assert process_events(qapp, lambda: panel._rows)
    panel._rows[0].btn_play.click()                  # Open
    assert process_events(qapp, lambda: len(panel._rows) == 3)
    assert played == []                              # nothing downloaded or played
    assert panel.link == PL_URL and panel.heading.text() == "Road trip  ·  3 videos"
    assert panel.add_all_btn.text() == "Add all (3)"
    assert not panel.kind_toggle.isVisibleTo(panel)   # a playlist's videos: no switch
    panel.btn_back.click()                           # back to the playlists found
    assert process_events(qapp, lambda: panel._rows and panel._rows[0].playlist)
    assert not panel.isHidden() and panel.kind_toggle.isVisibleTo(panel)
    assert calls[-1] == ("lofi", "youtube", True)
    panel.btn_back.click()                           # and from there, home
    assert panel.isHidden()


def test_the_switch_is_only_for_youtube_searches(qapp, monkeypatch):
    calls = fake(monkeypatch)
    panel = SearchResults()
    panel.kind_toggle.buttons["playlists"].setChecked(True)
    panel.set_source("soundcloud")
    panel.search("lofi")
    assert process_events(qapp, lambda: panel._rows)
    assert not panel.kind_toggle.isVisibleTo(panel)
    assert calls == [("lofi", "soundcloud", False)]   # SoundCloud's tracks, as before
    panel.show_link(PL_URL)                           # a pasted link: no switch either
    assert not panel.kind_toggle.isVisibleTo(panel)


def test_youtube_playlist_search_reads_playlists_only(monkeypatch):
    asked = []

    def extract(target, opts, keep=False):
        asked.append(target)
        return {"entries": [
            {"ie_key": "YoutubeTab", "id": "PLx", "title": "Mix", "channel": "Band",
             "url": "https://www.youtube.com/playlist?list=PLx",
             "thumbnails": [{"url": "https://i.ytimg.com/vi/a/hq720.jpg"}]},
            {"ie_key": "YoutubeTab", "id": "UCx", "title": "A channel",
             "url": "https://www.youtube.com/channel/UCx"}]}
    monkeypatch.setattr(ytdl.ytsearch, "_extract", extract)
    hits = ytdl.search("lofi beats", source="youtube", direct=True, playlists=True)
    assert asked == ["https://www.youtube.com/results?search_query=lofi+beats&sp=EgIQAw%3D%3D"]
    assert [(h.title, h.url, h.source) for h in hits] == [
        ("Mix", "https://www.youtube.com/playlist?list=PLx", ytdl.PLAYLIST)]
    assert hits[0].thumb == "https://i.ytimg.com/vi/a/hq720.jpg"


def test_add_all_on_a_found_playlist_queues_its_videos_without_opening(qapp, monkeypatch):
    fake(monkeypatch)
    queued = []
    panel = SearchResults()
    panel.add_all.connect(queued.append)
    panel.kind_toggle.buttons["playlists"].setChecked(True)
    panel.search("lofi")
    assert process_events(qapp, lambda: panel._rows)
    row = panel._rows[0]
    assert row.btn_add.isVisibleTo(row) and row.btn_add.text() == "Add all"
    row.btn_add.click()
    row.btn_add.click()                              # a double click lists it once
    assert process_events(qapp, lambda: queued)
    assert [r.url for r in queued[0]] == [f"https://www.youtube.com/watch?v=vid0000000{i}"
                                          for i in range(3)]
    assert len(queued) == 1 and row.btn_add.text() == "✓ 3 queued"
    assert panel._rows[0] is row and not panel.link   # never opened


def test_add_all_on_a_playlist_that_fails_says_so(qapp, monkeypatch):
    fake(monkeypatch)

    def gone(url, direct=False):
        raise ytdl.DownloadError("That playlist is empty, or its videos are private.")
    monkeypatch.setattr(ytdl, "lookup_all", gone)
    queued = []
    panel = SearchResults()
    panel.add_all.connect(queued.append)
    panel.kind_toggle.buttons["playlists"].setChecked(True)
    panel.search("lofi")
    assert process_events(qapp, lambda: panel._rows)
    row = panel._rows[0]
    row.btn_add.click()
    assert process_events(qapp, lambda: not panel._listing)
    assert queued == [] and not row._added


def test_a_playlist_cards_buttons_stack_when_their_words_dont_fit(qapp):
    """German's "Alle hinzufügen" beside "Öffnen" was cut off on a narrow card."""
    from PySide6.QtWidgets import QBoxLayout
    from soundboard.ui.sounds.ytcard import ResultRow
    row = ResultRow(ytdl.Result("PLx", "Mix", "Band", 0.0, source=ytdl.PLAYLIST, link=PL_URL))
    row.btn_add.setText("Alle hinzufügen")
    row.btn_play.setText("Öffnen")
    row.setFixedWidth(210)   # as the card grid gives it
    row.show()
    qapp.processEvents()
    assert row.buttons.direction() == QBoxLayout.Direction.TopToBottom
    inside = row.width() - 16                        # (its 8 px margins)
    for b in (row.btn_play, row.btn_add):            # each its own full row
        assert b.width() >= inside - 2               # (CI's stand-in font is wider)
    row.setFixedWidth(480)
    qapp.processEvents()
    assert row.buttons.direction() == QBoxLayout.Direction.LeftToRight


def _lockup(kind, badge):
    """A search result as YouTube's page lists it, with the text on its picture."""
    return {"contentId": "PLx", "contentType": kind, "contentImage": {
        "collectionThumbnailViewModel": {"primaryThumbnail": {"thumbnailViewModel": {
            "overlays": [{"thumbnailOverlayBadgeViewModel": {"thumbnailBadges": [
                {"thumbnailBadgeViewModel": {"text": badge}}]}}]}}}}}


def test_a_playlist_search_keeps_how_many_videos_each_has():
    """yt-dlp reads a found playlist's "7 videos" but drops it: the search keeps it."""
    from soundboard.online import ytworker

    class IE:
        def _extract_lockup_view_model(self, vm):
            return {"id": vm["contentId"]}
    ie = IE()

    class Ydl:
        def get_info_extractor(self, key):
            assert key == "YoutubeSearchURL"
            return ie
    ytworker._playlist_counts(Ydl())
    pl = "LOCKUP_CONTENT_TYPE_PLAYLIST"
    assert ie._extract_lockup_view_model(_lockup(pl, "7 videos"))["playlist_count"] == 7
    assert ie._extract_lockup_view_model(_lockup(pl, "1 video"))["playlist_count"] == 1
    assert ie._extract_lockup_view_model(_lockup(pl, "1,204 videos"))["playlist_count"] == 1204
    assert ie._extract_lockup_view_model(_lockup(pl, "1.2K videos"))["playlist_count"] == 1200
    assert "playlist_count" not in ie._extract_lockup_view_model(_lockup(pl, "Mix"))
    assert "playlist_count" not in ie._extract_lockup_view_model(
        _lockup("LOCKUP_CONTENT_TYPE_VIDEO", "3 videos"))
    assert ytworker.PLAYLIST_FILTER in "https://www.youtube.com/results?search_query=a&sp=EgIQAw%3D%3D"


def test_a_playlist_card_says_how_many_videos(qapp, monkeypatch):
    """A big playlist and a short one looked the same until opened: the card says."""
    from soundboard.ui.sounds.ytcard import ResultRow

    def extract(target, opts, keep=False):
        return {"entries": [{"id": "PLx", "title": "Mix", "channel": "Band",
                             "url": PL_URL, "playlist_count": 7}]}
    monkeypatch.setattr(ytdl.ytsearch, "_extract", extract)
    hit, = ytdl.search("lofi", source="youtube", direct=True, playlists=True)
    assert hit.videos == 7
    assert ResultRow(hit).sub.full == "7 videos · Band"
    one = ytdl.Result("PLx", "Mix", "Band", 0.0, source=ytdl.PLAYLIST, link=PL_URL, videos=1)
    assert ResultRow(one).sub.full == "1 video · Band"
    unsaid = ytdl.Result("PLx", "Mix", "Band", 0.0, source=ytdl.PLAYLIST, link=PL_URL)
    assert ResultRow(unsaid).sub.full == "Playlist · Band"
