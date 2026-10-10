"""Button click feedback: busy state, done flash, and back to normal."""
from PySide6.QtWidgets import QPushButton

from soundboard.ui import busy
from tests.conftest import process_events


def test_run_busy_shows_busy_then_done_then_idle(qapp):
    btn = QPushButton("Re-scan devices")
    seen = []

    def work():
        seen.append((btn.text(), busy.is_busy(btn)))
        return 3
    busy.run_busy(btn, "Scanning…", work, lambda n: f"✓ Found {n}", ms=50)
    assert btn.text() == "Scanning…" and busy.is_busy(btn)
    process_events(qapp, lambda: seen)
    assert seen == [("Scanning…", True)]
    assert btn.text() == "✓ Found 3" and not busy.is_busy(btn)
    process_events(qapp, lambda: btn.text() == "Re-scan devices")


def test_run_busy_ignores_a_second_click_while_running(qapp):
    btn = QPushButton("Go")
    calls = []
    busy.run_busy(btn, "…", lambda: calls.append(1))
    busy.run_busy(btn, "…", lambda: calls.append(2))
    process_events(qapp, lambda: calls)
    assert calls == [1]


def test_run_busy_says_when_it_failed(qapp, monkeypatch):
    btn = QPushButton("Go")
    errors = []
    monkeypatch.setattr("sys.excepthook", lambda *a: errors.append(a))

    def boom():
        raise OSError("nope")
    busy.run_busy(btn, "…", boom, ms=50)
    process_events(qapp, lambda: not busy.is_busy(btn))
    assert btn.text().startswith("Didn't work")
    assert errors   # still reported, not swallowed


def test_overlapping_flashes_restore_the_original_label(qapp):
    btn = QPushButton("Copy")
    busy.flash(btn, "✓ Copied", ms=40)
    busy.flash(btn, "✓ Copied", ms=80)
    process_events(qapp, lambda: btn.text() == "Copy")


def test_a_done_label_is_never_cut_off(qapp):
    """A "✓ Stopped" stands in for the button's icon, and where the layout can't make
    room for it (a full header) it's just the tick, never "✓ Stoppe"."""
    from PySide6.QtWidgets import QHBoxLayout, QWidget
    from soundboard.ui import icons
    host = QWidget()
    lay = QHBoxLayout(host)
    btn = QPushButton("Stop all")
    icons.set_icon(btn, "stop", size=14)
    lay.addWidget(btn)
    lay.addStretch(1)
    # a row with room to spare: a shown window never grows to fit a wider label (the
    # button's minimum width is held, busy._keep_width), so with a font or theme where
    # "✓ Stopped" is wider than "Stop all" and its icon, a row just wide enough for
    # the button had no room and got the tick
    host.resize(300, host.sizeHint().height())
    host.show()
    busy.flash(btn, "✓ Stopped", ms=200)
    assert btn.icon().isNull()
    assert process_events(qapp, lambda: btn.width() >= btn.sizeHint().width())
    assert btn.text() == "✓ Stopped"
    assert process_events(qapp, lambda: btn.text() == "Stop all")
    assert not btn.icon().isNull()
    host.setFixedWidth(60)   # no room to grow
    busy.flash(btn, "✓ Stopped with a much longer message", ms=200)
    assert process_events(qapp, lambda: btn.text() == "✓")
    assert process_events(qapp, lambda: btn.text() == "Stop all")
    host.close()


def test_hold_release(qapp):
    btn = QPushButton("Check")
    release = busy.hold(btn, "Checking…")
    assert busy.is_busy(btn)
    release("✓ Fine", ms=40)
    release("again")   # second release is a no-op
    assert not busy.is_busy(btn) and btn.text() == "✓ Fine"
    process_events(qapp, lambda: btn.text() == "Check")


def test_toast_shows_on_the_window_then_hides(qapp):
    from PySide6.QtWidgets import QWidget
    w = QWidget()
    w.resize(500, 300)
    busy.toast(w, "✓ Added 3 sounds", "ok", ms=50)
    t = w.findChild(busy._Toast)
    assert t is not None and t.isVisibleTo(w) and "Added 3" in t.text()
    assert t.y() + t.height() <= w.height() and t.property("tone") == "ok"
    busy.toast(w, "again", ms=50)               # reuses the one pill
    assert len(w.findChildren(busy._Toast)) == 1
    process_events(qapp, lambda: not t.isVisibleTo(w))


def test_toast_keeps_all_its_lines_when_the_window_shrinks_under_it(qapp):
    """Shown in a wide window, then the window shrank (into the mini player): the pill
    kept its one-line height and cut the rest of the text off."""
    from PySide6.QtWidgets import QWidget
    w = QWidget()
    w.resize(1280, 800)
    w.show()
    busy.toast(w, "Updating Onion Board's part of your mic so every app hears your "
               "sounds: click Yes when Windows asks.", ms=5000)
    t = w.findChild(busy._Toast)
    one_line = t.height()
    # 200 high, not 120: on CI's fonts the wrapped notice is taller than 120 (it fit here)
    for size in ((260, 200), (300, 400), (1280, 800)):
        w.resize(*size)
        qapp.processEvents()
        assert t.height() >= t.heightForWidth(t.width()), size
        assert 0 <= t.y() and t.y() + t.height() <= w.height(), size
    w.resize(260, 200)
    qapp.processEvents()
    assert t.height() > one_line
    w.close()


def test_open_url_says_when_it_could_not(qapp, monkeypatch):
    from PySide6.QtWidgets import QWidget
    w = QWidget()
    btn = QPushButton("Open", w)
    monkeypatch.setattr(busy.QDesktopServices, "openUrl", lambda _u: False)
    assert not busy.open_url("https://example.com/x", btn, failed="No browser")
    t = w.findChild(busy._Toast)
    assert "No browser" in t.text() and "example.com/x" in t.text()
    monkeypatch.setattr(busy.QDesktopServices, "openUrl", lambda _u: True)
    assert busy.open_url("https://example.com/x", btn, opened="✓ Opened")
    assert btn.text() == "✓ Opened"


def test_open_folder_tells_an_oserror(qapp):
    from PySide6.QtWidgets import QWidget
    w = QWidget()
    btn = QPushButton("Open folder", w)

    def make():
        raise PermissionError("denied")
    assert not busy.open_folder(make, btn)
    assert "denied" in w.findChild(busy._Toast).text()


def test_busy_keeps_the_focus_and_ignores_clicks(qapp):
    """Disabling the focused button jumped the focus to the combo box under Re-scan."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QComboBox, QVBoxLayout, QWidget
    w = QWidget()
    lay = QVBoxLayout(w)
    btn = QPushButton("Re-scan devices")
    combo = QComboBox()
    lay.addWidget(btn)
    lay.addWidget(combo)
    w.show()
    btn.setFocus()
    clicks = []
    btn.clicked.connect(lambda: clicks.append(1))
    release = busy.hold(btn, "Scanning…")
    assert btn.isEnabled() and w.focusWidget() is btn   # not moved on to the combo
    QTest.mouseClick(btn, Qt.LeftButton)
    QTest.keyClick(btn, Qt.Key_Space)
    assert clicks == []
    release()
    QTest.mouseClick(btn, Qt.LeftButton)
    assert clicks == [1] and w.focusWidget() is btn
    w.close()
