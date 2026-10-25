"""The red "didn't work" card (ui/kit/oops.py) and the places that show it."""
from conftest import process_events
from soundboard.ui.kit import oops
from test_mainwindow import window  # noqa: F401  (the real MainWindow fixture)


def test_the_card_says_what_and_what_to_do(qapp):
    tried = []
    card = oops.OopsPanel()
    card.show_problem("Couldn't open the store", "No connection.", lambda: tried.append(1))
    card.show()
    assert card.property("tone") == "error" and card.title.property("tone") == "error"
    assert card.line.text() == "No connection." and card.bun.sad == 1.0 and card.bun.sulk
    assert "close Onion Board and open it again" in card.what.text()
    assert card.btn_retry.isVisibleTo(card) and card.btn_report.isVisibleTo(card)
    card.btn_retry.click()
    assert tried == [1]
    card.show_problem("Nothing to share yet", "Start some music.", tone="")
    assert card.property("tone") == "" and not card.btn_report.isVisibleTo(card)
    assert not card.btn_retry.isVisibleTo(card)   # no retry given: no Try again


def test_an_errors_report_link_becomes_the_report_button(qapp, monkeypatch):
    opened = []
    monkeypatch.setattr(oops, "report", lambda win, url="": opened.append(url))
    text, url = oops.split_report('It broke. <a href="https://example.com/r?x=1">Report it</a>')
    assert text == "It broke." and url == "https://example.com/r?x=1"
    assert oops.split_report("Plain words.") == ("Plain words.", "")
    card = oops.OopsPanel()
    card.show_problem("t", 'It broke. <a href="https://example.com/r">Report it</a>')
    assert "Report it" not in card.line.text()
    card.btn_report.click()   # the form already filled in with what went wrong
    assert opened == ["https://example.com/r"]


def test_bun_goes_when_theres_no_room(qapp):
    card = oops.OopsPanel()
    page = oops.centred(card)
    card.show_problem("Couldn't open the store", "No connection.", lambda: None)
    page.resize(500, 600)
    page.show()
    process_events(qapp, lambda: False, 0.1)
    assert card.bun.isVisibleTo(page)
    page.resize(500, 180)
    process_events(qapp, lambda: False, 0.1)
    assert not card.bun.isVisibleTo(page) and card.title.isVisibleTo(page)


def test_a_narrow_card_stacks_its_buttons_instead_of_cutting_them(qapp):
    """A squeezed Radio map left the card 200 px wide: Report a problem was cut off."""
    card = oops.OopsPanel()
    card.show_problem("The radio couldn't connect", "Stations could not be loaded.",
                      lambda: None)
    card.show()
    card.setFixedWidth(oops.MAX_W)
    qapp.processEvents()
    side = card.btn_retry.geometry(), card.btn_report.geometry()
    assert side[0].top() == side[1].top()   # wide: side by side, as before
    card.setFixedWidth(200)
    card.resize(200, card.height_for(200))
    qapp.processEvents()
    retry, report = card.btn_retry.geometry(), card.btn_report.geometry()
    assert retry.bottom() < report.top()   # one over the other, Try again on top
    for b in (card.btn_retry, card.btn_report):
        assert b.width() >= b.sizeHint().width()   # whole words, nothing cut


def test_a_failed_search_shows_the_red_card_and_try_again_runs_it(qapp, monkeypatch):
    """The search can't get through: the red card says why, Try again searches the same
    words once more, and the results take its place."""
    from soundboard.online import ytdl
    from soundboard.ui.sounds.ytsearch import SearchResults
    calls = []

    def search(query, count=20, source="youtube", direct=False, start=1):
        calls.append(query)
        if len(calls) == 1:
            raise ConnectionError("The connection timed out")
        return [ytdl.Result(id="a", title="Lofi", channel="c", seconds=60.0, link="x")]
    monkeypatch.setattr(ytdl, "search", search)
    panel = SearchResults()
    panel.search("lofi beats")
    assert process_events(qapp, lambda: panel.failed and panel.oops.isVisibleTo(panel))
    assert panel.oops.property("tone") == "error" and not panel.title.isVisibleTo(panel)
    assert panel.oops.btn_retry.isVisibleTo(panel)
    panel.oops.btn_retry.click()
    assert process_events(qapp, lambda: len(calls) == 2 and not panel.loading.running())
    assert calls == ["lofi beats", "lofi beats"] and not panel.failed
    assert not panel.oops.isVisibleTo(panel)


def test_a_site_thats_down_gets_no_restart_the_app_advice(qapp, monkeypatch):
    """The site answered 5xx: waiting fixes that, closing Onion Board doesn't, so the
    card says only the site's trouble and Try again (no "close and open it again")."""
    from soundboard.online import ytdl
    from soundboard.ui.sounds.ytsearch import SearchResults
    calls = []

    def search(query, count=20, source="youtube", direct=False, start=1):
        calls.append(query)
        if len(calls) == 1:
            raise ytdl._readable(RuntimeError("HTTP Error 503: Service Unavailable"))
        raise ConnectionError("The connection timed out")
    monkeypatch.setattr(ytdl, "search", search)
    panel = SearchResults()
    panel.search("lofi beats")
    assert process_events(qapp, lambda: panel.failed and panel.oops.isVisibleTo(panel))
    assert "having trouble" in panel.oops.line.text()
    assert not panel.oops.what.isVisibleTo(panel) and not panel.oops.btn_report.isVisibleTo(panel)
    assert panel.oops.btn_retry.isVisibleTo(panel)
    panel.oops.btn_retry.click()   # now our side (a time-out): the advice is back
    assert process_events(qapp, lambda: len(calls) == 2 and panel.failed
                          and not panel.loading.running())
    assert panel.oops.what.isVisibleTo(panel)


def test_the_voice_strip_shows_while_the_voice_cant_work():
    """Logic only: problem() says why the voice that's on can't work, "" when it can."""
    from soundboard.ui.voice.voicepanel import VoicePanel

    class Fake:
        def __init__(self):
            self.engine = type("E", (), {"errors": {}})()
            self.chain = type("C", (), {"errors": {}})()
            self.on = True

        def is_active(self):
            return self.on
    f = Fake()
    assert VoicePanel.problem(f) == ""
    f.engine.errors["mic"] = "in use"
    assert VoicePanel.problem(f) == "Your mic couldn't be opened: in use"
    f.on = False
    assert VoicePanel.problem(f) == ""   # off: nothing to complain about
    f.on, f.engine.errors = True, {}
    f.chain.errors["pitch"] = "bad <value>"
    assert VoicePanel.problem(f) == "A voice effect stopped after an error: bad &lt;value&gt;"
    f.chain.errors = {}
    f.engine.mic_stream = None    # no mic (unplugged, none at all): said, not silent
    assert VoicePanel.problem(f).startswith("No mic is open")
    f.on = False
    assert VoicePanel.problem(f) == ""



def test_a_narrow_short_store_card_never_squeezes_its_words(window, qapp,  # noqa: F811
                                                            monkeypatch):
    """The Store tab narrow and short: Bun steps out, and the words keep the lines
    they wrap to (they were drawn on top of each other); with the room back, Bun too."""
    from soundboard.online import store

    def down(*_a, **_k):
        raise store.StoreError("Couldn't reach the sound store.")
    monkeypatch.setattr(store, "_request", down)
    w = window
    w.show()
    w.tabs.setCurrentWidget(w.store)
    w.store._problem("Couldn't open the store",
                     "Couldn't reach the sound store. Check your internet and try again.")
    card = w.store.oops
    for height, bun in ((640, True), (470, False)):
        w.resize(440, height)
        process_events(qapp, lambda: False, 0.3)
        assert w.store.stack.currentWidget() is w.store.oops_page
        for label in (card.title, card.line, card.what):
            assert label.height() >= label.heightForWidth(label.width()), (height, label.text())
        assert card.bun.isVisibleTo(card) == bun
