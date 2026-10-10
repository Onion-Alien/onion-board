"""Apps ordering and category views preserve the existing audio cards."""
import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent

from soundboard.appaudio import App
from soundboard.ui import appspanel
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

    monkeypatch.setattr(appspanel, "QDrag", Drag)
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
    assert not tab.grid.headings["Browsers"].isHidden()
    tab.hide()
