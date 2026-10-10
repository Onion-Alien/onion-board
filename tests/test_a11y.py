"""Screen-reader names for icon-only controls (soundboard.ui.a11y)."""
import pytest
from PySide6.QtWidgets import QLineEdit, QPushButton, QSlider, QVBoxLayout, QWidget

from soundboard.ui import a11y
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
