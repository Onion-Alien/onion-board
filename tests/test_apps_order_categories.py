"""Apps ordering and category views preserve the existing audio cards."""
import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent

from soundboard.audio.appaudio import App
from soundboard.ui import appspanel, approw
from tests.test_appspanel import tab as app_tab_fixture


@pytest.fixture
def tab(qapp, monkeypatch):
    yield from app_tab_fixture.__wrapped__(qapp, monkeypatch)


def order(tab):
    return [tab.grid.itemAt(i).widget().key for i in range(tab.grid.count())]


@pytest.mark.parametrize(("exe", "category"), [
    ("FIREFOX.EXE", "Browsers"), ("msedge.exe", "Browsers"),
    ("Spotify.exe", "Music & media"), ("vlc.exe", "Music & media"),
    ("Discord.exe", "Calls & chat"), ("ms-teams.exe", "Calls & chat"),
    ("cs2.exe", "Games"), ("eldenring.exe", "Games"),
    ("unknown.exe", "Other"), ("my-firefox-helper.exe", "Other"),
])
def test_categories(exe, category):
    assert appspanel.app_category(exe) == category


def test_reorder_survives_rescans_and_new_apps_without_saving(tab):
    apps = [App(1, "firefox.exe"), App(2, "msedge.exe"), App(3, "brave.exe")]
    tab._on_apps(apps)
    source, target = tab.rows["brave.exe"], tab.rows["firefox.exe"]
    source.btn_send.setChecked(True)
    capture = source.capture
    saved = len(tab.saved)
    tab._reorder_apps(source, target, True)
    tab._on_apps(list(reversed(apps)) + [App(4, "vlc.exe")])
    assert order(tab) == ["brave.exe", "firefox.exe", "msedge.exe", "vlc.exe"]
    assert source.capture is capture and not capture.stopped and source.sending
    assert len(tab.saved) == saved
    tab._reorder_apps(source, tab.rows["msedge.exe"], False)
    assert order(tab) == ["firefox.exe", "msedge.exe", "brave.exe", "vlc.exe"]


def test_category_sections_group_cards_and_hide_empty_headings(tab, qapp, monkeypatch):
    apps = [App(1, "firefox.exe"), App(2, "spotify.exe"), App(3, "custom.exe")]
    tab._on_apps(apps)
    music = tab.rows["spotify.exe"]
    music.btn_send.setChecked(True)
    capture = music.capture
    apps += [App(4, "vlc.exe")]
    monkeypatch.setattr(appspanel.appaudio, "list_apps", lambda **_: apps)
    tab._on_apps(apps)
    tab.resize(1200, 800)
    tab.show()
    qapp.processEvents()
    assert not tab.grid.headings["Browsers"].isHidden()
    assert tab.grid.headings["Games"].isHidden()
    assert tab.rows["spotify.exe"].y() == tab.rows["vlc.exe"].y()
    assert tab.rows["firefox.exe"].y() < music.y() < tab.rows["custom.exe"].y()
    assert music.capture is capture and music.sending and not capture.stopped
    assert all(not row.isHidden() for row in tab.rows.values())
    assert order(tab) == ["firefox.exe", "spotify.exe", "custom.exe", "vlc.exe"]
    tab.hide()


def test_left_header_drag_has_threshold_and_buttons_are_not_drag_handles(tab, monkeypatch):
    tab._on_apps([App(1, "firefox.exe")])
    row = tab.rows["firefox.exe"]
    drags = []

    class Drag:
        def __init__(self, source):
            drags.append(source)

        def setMimeData(self, mime):
            assert bytes(mime.data(appspanel.APP_DRAG_MIME)) == b"firefox.exe"

        def setPixmap(self, pixmap):
            pass

        def exec(self, action):
            assert action == Qt.MoveAction

    monkeypatch.setattr(approw, "QDrag", Drag)
    press = QMouseEvent(QEvent.MouseButtonPress, QPointF(10, 10), QPointF(10, 10),
                        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    move = QMouseEvent(QEvent.MouseMove, QPointF(50, 10), QPointF(50, 10),
                       Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
    row.eventFilter(row.btn_send, press)
    row.eventFilter(row.btn_send, move)
    assert not drags
    row.eventFilter(row.name, press)
    small_move = QMouseEvent(QEvent.MouseMove, QPointF(11, 10), QPointF(11, 10),
                            Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
    row.eventFilter(row.name, small_move)
    assert not drags
    row.eventFilter(row.name, move)
    assert drags == [row]


def test_drop_reorders_on_either_half_and_rejects_foreign_sources(tab):
    tab._on_apps([App(1, "firefox.exe"), App(2, "msedge.exe")])
    source, target = tab.rows.values()

    class Drop:
        accepted = False
        origin = None
        x = 0

        def source(self):
            return self.origin

        def mimeData(self):
            from PySide6.QtCore import QMimeData
            mime = QMimeData()
            mime.setData(appspanel.APP_DRAG_MIME, b"firefox.exe")
            return mime

        def setDropAction(self, action):
            assert action == Qt.MoveAction

        def accept(self):
            self.accepted = True

        def ignore(self):
            self.accepted = False

        def isAccepted(self):
            return self.accepted

        def position(self):
            return QPointF(self.x, 0)

    drop = Drop()
    drop.origin = source
    drop.x = target.width()
    target.dropEvent(drop)
    assert drop.accepted and order(tab) == ["msedge.exe", "firefox.exe"]
    drop.x = 0
    target.dropEvent(drop)
    assert order(tab) == ["firefox.exe", "msedge.exe"]
    drop.origin = None
    target.dropEvent(drop)
    assert not drop.accepted


def test_big_clip_view_restores_category_sections(tab, qapp, monkeypatch):
    apps = [App(1, "firefox.exe"), App(2, "spotify.exe")]
    monkeypatch.setattr(appspanel.appaudio, "list_apps", lambda **_: apps)
    tab.resize(1000, 800)
    tab.show()
    tab._on_apps(apps)
    row = tab.rows["firefox.exe"]
    row.btn_clip.setChecked(True)
    tab._set_big(row, True)
    qapp.processEvents()
    assert not row.isHidden() and tab.rows["spotify.exe"].isHidden()
    assert all(label.isHidden() for label in tab.grid.headings.values())
    tab._set_big(row, False)
    qapp.processEvents()
    assert not tab.rows["spotify.exe"].isHidden()
    tab.hide()


def test_cross_category_drag_moves_category(tab):
    apps = [App(1, "firefox.exe"), App(2, "spotify.exe")]
    tab._on_apps(apps)
    firefox = tab.rows["firefox.exe"]
    spotify = tab.rows["spotify.exe"]
    assert firefox.category == "Browsers"
    assert spotify.category == "Music & media"

    # Drag firefox over spotify
    tab._reorder_apps(firefox, spotify, before=True)
    assert firefox.category == "Music & media"
    assert order(tab) == ["firefox.exe", "spotify.exe"]
    assert tab.cfg.apps["firefox.exe"]["category"] == "Music & media"


def test_drop_card_on_category_heading(tab):
    apps = [App(1, "custom.exe")]
    tab._on_apps(apps)
    custom = tab.rows["custom.exe"]
    assert custom.category == "Other"

    # Drop onto Browsers heading
    tab._on_card_dropped_on_category(custom, "Browsers")
    assert custom.category == "Browsers"
    assert tab.cfg.apps["custom.exe"]["category"] == "Browsers"


def test_reorder_category_headings(tab):
    assert tab.grid.category_order[0] == "Browsers"
    assert "Other" in tab.grid.category_order

    tab._on_category_reordered("Other", "Browsers", before=True)
    assert tab.grid.category_order[0] == "Other"
    assert tab.cfg.apps_categories[0] == "Other"


def test_a_program_saved_in_a_category_that_is_gone_still_gets_a_place(qapp, monkeypatch):
    """A remembered program whose category isn't in the list any more (a restored
    backup, a category deleted while it wasn't listed) goes to its usual one: the
    layout only places the categories it knows, so the card would vanish."""
    from soundboard.sounds.library import Config
    from tests.test_appspanel import AppsTab, Engine, FakeCapture, Meter
    monkeypatch.setattr(appspanel.appaudio, "AppCapture", FakeCapture)
    monkeypatch.setattr(appspanel.appaudio, "list_apps", lambda strict=False, **_: [])
    cfg = Config()
    cfg.apps = {"spotify.exe": {"vol": 1.0, "category": "Gone"}}
    cfg.apps_categories = ["Browsers", "Other"]
    t = AppsTab(Engine(), cfg, lambda: None, Meter)
    try:
        row = t.rows["spotify.exe"]
        assert row.category == "Music & media" and row.category in t.grid.category_order
    finally:
        t.shutdown()


def test_custom_category_lifecycle(tab):
    apps = [App(1, "custom.exe")]
    tab._on_apps(apps)
    custom = tab.rows["custom.exe"]

    # 1. Add custom category
    tab.grid.add_category("Work")
    tab.cfg.apps_categories = list(tab.grid.category_order)
    assert "Work" in tab.grid.category_order
    assert "Work" in tab.grid.headings

    # 2. Move card to custom category
    tab._move_row_to_category(custom, "Work")
    assert custom.category == "Work"

    # 3. Rename custom category
    tab.grid.rename_category("Work", "Office")
    for row in tab.rows.values():
        if row.category == "Work":
            row.category = "Office"
    assert "Office" in tab.grid.category_order
    assert "Work" not in tab.grid.category_order
    assert custom.category == "Office"

    # 4. Delete custom category -> moves cards to Other
    tab._on_delete_category("Office")
    assert "Office" not in tab.grid.category_order
    assert custom.category == "Other"



def test_new_category_button_opens_a_name_box_in_its_place(tab, qapp):
    """The Apps tab's "+ Category" swaps itself for a name box: Enter adds the
    category, Esc doesn't. No pop-up."""
    from PySide6.QtTest import QTest
    tab.show()
    box = tab.cat_name_box
    tab.btn_add_cat.click()
    qapp.processEvents()
    assert box.isVisible() and not tab.btn_add_cat.isVisible()
    QTest.keyClicks(box, "Work")
    QTest.keyClick(box, Qt.Key.Key_Escape)
    assert "Work" not in tab.grid.category_order and tab.btn_add_cat.isVisible()
    tab.btn_add_cat.click()
    QTest.keyClicks(box, "Work")
    QTest.keyClick(box, Qt.Key.Key_Return)
    assert "Work" in tab.grid.category_order and "Work" in tab.cfg.apps_categories
    assert not box.isVisible() and tab.btn_add_cat.isVisible()


def test_category_headings_have_a_keyboard_way_to_their_menu(tab, qapp, monkeypatch):
    """Tab reaches a heading (in the order shown: heading, its cards, the next one), it
    shows it has the focus, and the Menu key or Shift+F10 opens Rename / Delete."""
    from PySide6.QtGui import QKeySequence, QShortcut
    apps = [App(1, "firefox.exe"), App(2, "spotify.exe"), App(3, "vlc.exe")]
    monkeypatch.setattr(appspanel.appaudio, "list_apps", lambda **_: apps)
    tab.grid.add_category("Work")
    tab._wire_headings()
    tab.resize(1000, 900)
    tab.show()
    tab._on_apps(apps)
    qapp.processEvents()
    browsers, music = tab.grid.headings["Browsers"], tab.grid.headings["Music & media"]
    assert browsers.focusPolicy() == Qt.TabFocus   # a click is the drag, not focus
    firefox, spotify = tab.rows["firefox.exe"], tab.rows["spotify.exe"]
    stops = [w for w in _focus_chain(browsers) if w.focusPolicy() & Qt.TabFocus]
    assert firefox.isAncestorOf(stops[0])                 # its card, not the next heading
    after_firefox = [w for w in stops if not firefox.isAncestorOf(w)]
    assert after_firefox[0] is music and spotify.isAncestorOf(after_firefox[1])
    tab.grid.reorder_categories("Music & media", "Browsers", True)   # follows a reorder
    tab._layout_apps()
    qapp.processEvents()
    first = [w for w in _focus_chain(music) if w.focusPolicy() & Qt.TabFocus][:1]
    assert spotify.isAncestorOf(first[0])

    plain = browsers.grab().toImage()
    browsers.setFocus(Qt.TabFocusReason)
    qapp.processEvents()
    assert browsers.hasFocus() and browsers.grab().toImage() != plain   # its focus ring

    seen = []

    class Shown(approw.QMenu):
        def exec(self, *a):
            seen.append([x.text() for x in self.actions() if x.text()])
    monkeypatch.setattr(approw, "QMenu", Shown)
    for heading, want in ((browsers, ["Rename category"]),
                          (tab.grid.headings["Work"], ["Rename category", "Delete category"])):
        keys = {sc.key().toString(): sc for sc in heading.findChildren(QShortcut)}
        assert QKeySequence(Qt.Key_Menu).toString() in keys and "Shift+F10" in keys
        assert all(sc.context() == Qt.WidgetShortcut for sc in keys.values())
        for sc in keys.values():
            sc.activated.emit()
        assert seen[-2:] == [want, want]


def _focus_chain(start, n=60):
    w, out = start, []
    for _ in range(n):
        w = w.nextInFocusChain()
        out.append(w)
    return out


def test_built_in_category_names_show_in_the_language_and_save_in_english(qapp, monkeypatch):
    from soundboard import i18n
    from soundboard.audio.engine import Engine
    from soundboard.sounds.library import Config
    from soundboard.ui.widgets import Meter
    monkeypatch.setattr(appspanel.appaudio, "list_apps", lambda strict=False, **_: [])
    i18n.set_language("de")
    try:
        cfg = Config()
        t = appspanel.AppsTab(Engine(), cfg, lambda: None, Meter)
        t._on_apps([App(1, "cs2.exe"), App(2, "spotify.exe")])
        assert t.grid.headings["Games"].text() == "Spiele"
        assert t.grid.headings["Music & media"].text() == "Musik & Medien"
        assert t.rows["cs2.exe"].category == "Games"          # the saved key stays English
        shown = []

        class Shown(approw.QMenu):
            def exec(self, *a):
                for act in self.actions():
                    if act.menu() is not None:
                        shown.extend(x.text() for x in act.menu().actions())
        monkeypatch.setattr(approw, "QMenu", Shown)
        t.rows["cs2.exe"]._show_card_menu(t.rows["cs2.exe"].rect().center())
        assert "Spiele" in shown and "Musik && Medien" in shown and "Games" not in shown
        asked = []

        def answer(text):
            def get_text(*a, **k):
                asked.append(k.get("text"))
                return text, True
            return get_text
        monkeypatch.setattr(appspanel.QInputDialog, "getText", answer("Spiele"))
        t._on_rename_category("Games")                       # OK on the shown name: no change
        assert asked == ["Spiele"] and "Games" in t.grid.category_order
        t._add_category("Spiele")                            # nor a second "Spiele"
        assert "Spiele" not in t.grid.category_order
        monkeypatch.setattr(appspanel.QInputDialog, "getText", answer("Shooter"))
        t._on_rename_category("Games")
        assert "Shooter" in t.grid.category_order and t.rows["cs2.exe"].category == "Shooter"
        assert t.grid.headings["Shooter"].text() == "Shooter"
        t.shutdown()
    finally:
        i18n.set_language("en")


def test_tab_order_reads_each_cards_controls_fresh(tab, qapp, monkeypatch):
    """Each card's controls are read fresh for the Tab order. A list kept on the card
    held one Qt had deleted: setTabOrder raised inside the layout pass, and that broke
    PySide badly enough to crash closing the clip editor's big view (overridepin.py)."""
    import shiboken6
    from PySide6.QtWidgets import QPushButton
    apps = [App(1, "firefox.exe"), App(2, "spotify.exe")]
    monkeypatch.setattr(appspanel.appaudio, "list_apps", lambda **_: apps)
    tab.resize(1000, 900)
    tab.show()
    tab._on_apps(apps)
    qapp.processEvents()
    row = tab.rows["firefox.exe"]
    browsers = tab.grid.headings["Browsers"]

    def resync():
        tab.grid._tab_key = []   # as when the shown order changes
        tab.grid._place(tab.grid.geometry(), move=True)

    gone = QPushButton("gone", row)
    resync()
    assert gone in _focus_chain(browsers)
    shiboken6.delete(gone)
    resync()                    # no "already deleted" from setTabOrder
    stops = [w for w in _focus_chain(browsers) if w.focusPolicy() & Qt.TabFocus]
    assert row.isAncestorOf(stops[0]) and row.vol.slider in stops
