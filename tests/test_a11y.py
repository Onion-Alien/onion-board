"""Screen-reader names for icon-only controls (soundboard.ui.kit.a11y)."""
import pytest
from PySide6.QtWidgets import QLineEdit, QPushButton, QSlider, QVBoxLayout, QWidget

from soundboard.ui.kit import a11y
from test_mainwindow import window as main_window  # noqa: F401  (the real MainWindow)


@pytest.fixture
def window(main_window):  # noqa: F811
    return main_window


def test_short_names_from_tooltips():
    assert a11y.short("Stop — stops every sound") == "Stop"
    assert a11y.short("Play / pause") == "Play / pause"
    assert a11y.short("Pad size. Drag to resize.") == "Pad size"
    assert a11y.plain("<span style='x'>Mic &amp; cable</span>") == "Mic & cable"
    assert len(a11y.short("x" * 300)) == a11y.MAX_NAME


def test_names_what_has_none_and_leaves_the_rest(qapp):
    root = QWidget()
    lay = QVBoxLayout(root)
    icon_btn, text_btn, sym_btn, named = (QPushButton(), QPushButton("Save"),
                                          QPushButton("✕"), QPushButton())
    icon_btn.setToolTip("Stop — stops the sound")
    sym_btn.setToolTip("Clear")
    named.setToolTip("Tooltip")
    named.setAccessibleName("Chosen by hand")
    slider = QSlider()
    slider.setToolTip("Pad size")
    edit = QLineEdit()
    edit.setPlaceholderText("Search sounds")
    for w in (icon_btn, text_btn, sym_btn, named, slider, edit):
        lay.addWidget(w)
    a11y.label_tree(root, force=True)
    assert icon_btn.accessibleName() == "Stop"
    assert text_btn.accessibleName() == ""           # Qt reads "Save"
    assert sym_btn.accessibleName() == "Clear"       # "✕" says nothing
    assert named.accessibleName() == "Chosen by hand"
    assert slider.accessibleName() == "Pad size"
    assert edit.accessibleName() == "Search sounds"
    icon_btn.setToolTip("Pause")                     # made here: follows the tooltip
    a11y.label_tree(root, force=True)
    assert icon_btn.accessibleName() == "Pause"


def test_main_window_icon_buttons_all_have_names(window):
    from PySide6.QtWidgets import QAbstractButton
    unnamed = [b for b in window.findChildren(QAbstractButton)
               if not a11y.has_words(b.text()) and not b.accessibleName() and b.toolTip()]
    assert unnamed == []
    assert window.btn_st.accessibleName() == "Stop"


def test_a_focus_change_in_a_tab_goes_over_only_that_tab(qapp):
    """The whole main window is ~1300 widgets with a big board (4 ms a focus change):
    focus inside a tab names that tab's controls, outside any tab the whole window's."""
    from PySide6.QtWidgets import QTabWidget
    root = QWidget()
    lay = QVBoxLayout(root)
    tabs = QTabWidget()
    pages = [QWidget(), QWidget()]
    btns = []
    for i, page in enumerate(pages):
        b = QPushButton(parent=page)
        b.setToolTip(f"Tab {i} button")
        btns.append(b)
        tabs.addTab(page, str(i))
    outside = QPushButton()
    outside.setToolTip("Outside")
    lay.addWidget(tabs)
    lay.addWidget(outside)
    assert a11y.scope(btns[0]) is pages[0] and a11y.scope(outside) is root
    a11y.label_tree(btns[0])
    assert btns[0].accessibleName() == "Tab 0 button"
    assert btns[1].accessibleName() == "" and outside.accessibleName() == ""
    a11y.label_tree(outside)
    assert btns[1].accessibleName() == "Tab 1 button" and outside.accessibleName() == "Outside"


def test_every_tab_stop_on_the_main_pages_has_a_name(window):
    """A screen reader says each Tab stop's name; a bare one is only "scroll area" or
    "tab bar". Scroll areas whose controls are stops of their own aren't stops."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QAbstractButton, QAbstractScrollArea, QLabel
    buddied = {id(lab.buddy()) for lab in window.findChildren(QLabel) if lab.buddy()}

    def said(w):
        text = w.text() if isinstance(w, (QAbstractButton, QLineEdit)) else ""
        return bool(w.accessibleName() or a11y.has_words(text) or id(w) in buddied)

    for page in (window.sounds_page, window.apps, window.voice, window.setup_page):
        window.tabs.setCurrentWidget(page)
        a11y.label_tree(window, force=True)
        stops, w = [], window.nextInFocusChain()
        while w is not window:
            if ((w.focusPolicy() & Qt.FocusPolicy.TabFocus) == Qt.FocusPolicy.TabFocus
                    and w.isEnabled() and w.isVisibleTo(window)):
                stops.append(w)
            w = w.nextInFocusChain()
        assert stops
        assert [w for w in stops if not said(w)] == [], type(page).__name__
        assert not [w for w in stops if isinstance(w, QAbstractScrollArea)]
    assert window.catctl.cat_tabs.accessibleName() == "Categories"
    assert window._pad_scroll.accessibleName() == "Your sounds"


def test_the_sounds_page_and_the_hear_switch_have_names(window, qapp):
    """The Sounds page takes the focus when switched to (its Ctrl+V), and a narrow
    window blanks the Hear what they hear switch's words: both still have a name."""
    assert window.sounds_page.accessibleName() == "Sounds"
    b = window.btn_check
    b.setText("")   # what a narrow window does
    assert b.accessibleName() == "Hear what they hear"
    b.setChecked(True)
    qapp.processEvents()
    assert b.accessibleName() == "Stop hearing it"
    b.setChecked(False)
    qapp.processEvents()
    assert b.accessibleName() == "Hear what they hear"


def test_every_tab_stop_in_settings_has_a_name(window):
    """The same on every Settings page: a drop-down with only a label beside it was read
    as a bare "combo box" (Audio buffering, the device boxes, quality, the overlay's)."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QAbstractButton, QAbstractScrollArea, QLabel
    window.resize(1180, 760)
    window.show()
    window.setctl.open_settings("general")
    dlg = window.setctl._settings_dlg
    missing = {}
    for key in [k for k in dlg._page_keys if k != dlg.ADVANCED]:
        dlg.show_page(key)
        a11y.label_tree(window, force=True)
        buddied = {id(lab.buddy()) for lab in window.findChildren(QLabel) if lab.buddy()}
        w = window.nextInFocusChain()
        while w is not window:
            if ((w.focusPolicy() & Qt.FocusPolicy.TabFocus) == Qt.FocusPolicy.TabFocus
                    and w.isEnabled() and w.isVisibleTo(window)
                    and not isinstance(w, QAbstractScrollArea)):
                text = w.text() if isinstance(w, (QAbstractButton, QLineEdit)) else ""
                if not (w.accessibleName() or a11y.has_words(text) or id(w) in buddied):
                    shown = getattr(w, "currentText", lambda: "")()
                    missing.setdefault(key, []).append(f"{type(w).__name__} {shown!r}")
            w = w.nextInFocusChain()
    window.setctl.close_settings()
    assert missing == {}


def test_the_search_box_says_it_takes_links_too(window, monkeypatch):
    """A narrow window's hint is only "Search", but the box also takes a pasted link:
    its name says both. With finding sounds online off, it only searches yours."""
    from soundboard.ui.kit.widgets import fit_placeholder
    box = window.search
    fit_placeholder(box, "Search")   # what a narrow window shows
    a11y.label_tree(window, force=True)
    assert box.accessibleName() == "Search sounds or paste a link"
    monkeypatch.setattr(window.ytresults, "available", lambda: False)
    window.netctl._search_follow_switch()
    assert box.accessibleName() == "Search your sounds"


def test_up_next_chip_is_a_button_to_a_screen_reader(window, monkeypatch, qapp):
    """It looked and clicked like a button but read as a plain frame."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QAccessible
    from PySide6.QtTest import QTest
    from test_board_controls import playing
    w = window
    w.resize(1200, 760)
    w.show()
    playing(monkeypatch, w, ["s0"])
    w.playctl._queue = ["s1", "s0", "s1"]
    w.playctl._update_chips(w.engine.playing())
    chip = w._up_next_chip
    assert isinstance(chip, QPushButton)
    face = QAccessible.queryAccessibleInterface(chip)
    assert face.role() == QAccessible.Role.Button
    assert face.text(QAccessible.Text.Name) == "Up next 3"
    assert chip.sizeHint().width() > 60 and chip.height() == 30   # the labels fit in it
    for key in (Qt.Key.Key_Space, Qt.Key.Key_Return):
        QTest.keyClick(chip, key)
        qapp.processEvents()
        assert w._up_next_popup.isVisible()
        w._up_next_popup.close()
        qapp.processEvents()
        chip = w._up_next_chip
