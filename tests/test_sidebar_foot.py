"""The rail's foot: alerts above the on-air controls, Settings with the open / shut
arrow beside it."""
import pytest
from PySide6.QtWidgets import QApplication, QBoxLayout, QLabel, QPushButton, QWidget

from test_mainwindow import window  # noqa: F401

from soundboard.ui.window.sidebar import SideRail, SideTabs


def _rail(qapp, is_open):
    tabs = SideTabs()
    tabs.addTab(QWidget(), "One")
    alert, live, gear = QPushButton(), QPushButton(), QPushButton("Settings")
    alert.setObjectName("pill")
    rail = SideRail(tabs, QWidget(), QLabel(), QLabel(), [], is_open, [gear], status=[live],
                    alerts=[alert])
    rail.resize(rail.width(), 600)
    alert.hide()
    rail.show()
    QApplication.processEvents()
    return rail, alert, live, gear


def test_alerts_come_first_and_the_line_under_them_follows_them(qapp):
    rail, alert, live, _gear = _rail(qapp, True)
    assert rail.status == [alert, live]   # drawn (and tabbed) in this order
    assert rail.div_alerts.isHidden()
    alert.show()
    QApplication.processEvents()
    QApplication.processEvents()
    assert not rail.div_alerts.isHidden()
    assert alert.geometry().bottom() < rail.div_alerts.geometry().top() < live.geometry().top()
    alert.hide()
    QApplication.processEvents()
    QApplication.processEvents()
    assert rail.div_alerts.isHidden()
    rail.close()


def test_settings_and_the_arrow_share_a_row_open_and_stack_shut(qapp):
    rail, _alert, _live, gear = _rail(qapp, True)
    assert rail._foot_box.direction() == QBoxLayout.LeftToRight
    assert gear.geometry().center().y() == rail.toggle.geometry().center().y()
    rail.set_open(False)
    QApplication.processEvents()
    assert rail._foot_box.direction() == QBoxLayout.TopToBottom
    assert gear.geometry().bottom() < rail.toggle.geometry().top()
    rail.close()


def test_settings_is_its_icon_only_and_selected_round_it(qapp):
    """Open or shut, Settings is just the cog (its name for screen readers); showing its page,
    it gets the current tab's fill and the tabs lose theirs. The arrow stays at the
    far side of the open rail."""
    from soundboard.ui.window.sidebar import BUTTON_W
    rail, _alert, _live, gear = _rail(qapp, True)
    gear.setProperty("railtext", "Settings")
    rail.set_open(False)
    QApplication.processEvents()
    for is_open in (True, False):
        rail.set_open(is_open)
        QApplication.processEvents()
        assert gear.text() == ""
        assert gear.accessibleName() == "Settings" and gear.width() == BUTTON_W
    rail.set_open(True)
    QApplication.processEvents()
    assert rail.toggle.geometry().right() > gear.geometry().right() + BUTTON_W
    rail.select_foot(gear)
    assert gear.isChecked() and not rail.buttons[0].isChecked()
    rail.select_foot(None)
    assert not gear.isChecked() and rail.buttons[0].isChecked()
    rail.close()


def test_the_line_over_settings_has_the_same_gap_on_both_sides(qapp):
    """Stop all's icon over the line and Settings' icon under it sit as far from it,
    open and shut (the cog is as tall as the buttons over it: its square is painted)."""
    from PySide6.QtWidgets import QFrame
    from soundboard.ui.window.sidebar import ICON
    tabs = SideTabs()
    tabs.addTab(QWidget(), "One")
    stop, gear = QPushButton("Stop all"), QPushButton()
    stop.setObjectName("danger")
    rail = SideRail(tabs, QWidget(), QLabel(), QLabel(), [], True, [gear], status=[stop])
    rail.resize(rail.width(), 600)
    rail.show()
    for is_open in (True, False):
        rail.set_open(is_open)
        QApplication.processEvents()
        line = [f for f in rail.findChildren(QFrame, "raildiv") if f.isVisible()][-1]
        y = line.geometry().top()
        above = y - (stop.geometry().center().y() + ICON // 2)
        below = gear.geometry().center().y() - ICON // 2 - y
        assert abs(above - below) <= 1, (is_open, above, below)
        assert gear.height() == stop.height()
    rail.close()


def test_a_rail_without_alerts_has_no_stray_window(qapp):
    tabs = SideTabs()
    tabs.addTab(QWidget(), "One")
    rail = SideRail(tabs, QWidget(), QLabel(), QLabel(), [], False)
    rail.show()
    QApplication.processEvents()
    assert not rail.div_alerts.isVisible() and rail.div_alerts.parentWidget() is None
    rail.close()


def test_shut_rail_hides_the_alerts_and_shows_a_dot_instead(qapp):
    rail, alert, _live, _gear = _rail(qapp, True)
    alert.setProperty("railfull", "Not connected")
    alert.show()
    QApplication.processEvents()
    QApplication.processEvents()
    assert alert.isVisible() and not rail.toggle.property("dot")
    rail.set_open(False)
    QApplication.processEvents()
    assert not alert.isVisible()                  # out of sight shut...
    assert rail.toggle.property("dot")            # ...but not forgotten
    assert "Not connected" in rail.toggle.toolTip()
    rail.set_open(True)
    QApplication.processEvents()
    assert alert.isVisible() and not rail.toggle.property("dot") and rail.toggle.toolTip() == ""
    rail.close()


def test_shut_tabs_have_a_hover_name_with_their_key_and_open_ones_do_not(qapp):
    tabs = SideTabs()
    for name in ("One", "Two"):
        tabs.addTab(QWidget(), name)
    rail = SideRail(tabs, QWidget(), QLabel(), QLabel(), [], False)
    rail.show()
    QApplication.processEvents()
    assert [b.toolTip() for b in rail.buttons] == ["One  (Ctrl+1)", "Two  (Ctrl+2)"]
    rail.set_open(True)
    assert [b.toolTip() for b in rail.buttons] == ["", ""]
    rail.close()


def test_ctrl_numbers_and_ctrl_tab_move_between_tabs(window):  # noqa: F811
    window.show()
    QApplication.processEvents()
    shown = [b for b in window.rail.buttons if b.isVisible()]
    assert len(shown) >= 3
    window.tabctl._go_tab(1, absolute=True)
    assert shown[1].isChecked()
    window.tabctl._go_tab(1)
    assert shown[2].isChecked()
    window.tabctl._go_tab(-1)
    assert shown[1].isChecked()
    window.tabctl._go_tab(-2)   # wraps round
    assert shown[-1].isChecked()
    window.tabctl._go_tab(99, absolute=True)   # no such tab: nothing happens
    assert shown[-1].isChecked()


def test_a_tabs_right_click_menu_sets_its_own_key_instead_of_ctrl_number(window, monkeypatch):  # noqa: F811
    """Ctrl+1... clash with pads' keys: a tab's menu gives it another key, and its
    Ctrl+number then does nothing (the pad's key plays only the pad)."""
    from soundboard.ui.window import tabcontrol
    window.show()
    QApplication.processEvents()
    tabctl = window.tabctl
    shown = tabctl._shown_buttons()
    first, second = (tabcontrol.TAB_KEYS[b.index] for b in shown[:2])
    assert tabctl.tab_key(first) == "ctrl+1"
    menu = tabctl.tab_menu(shown[0].index)
    assert "Turn into Bun" not in [a.text() for a in menu.actions()]
    hk = menu.actions()[-1].menu()
    assert menu.actions()[-1].text() == "Hotkey: Ctrl+1"
    assert [a.text() for a in hk.actions()] == ["Change", "Remove hotkey"]
    monkeypatch.setattr(tabcontrol.HotkeyDialog, "exec", lambda d: setattr(
        d, "result_combo", "alt+f5") or True)
    hk.actions()[0].trigger()                       # Change: asks, Alt+F5 picked
    assert window.cfg.tab_keys == {first: "alt+f5"}
    assert tabctl.tab_key(first) == "alt+f5" and tabctl.tab_key(second) == "ctrl+2"
    shown[1].click()
    tabctl._ctrl_number(1)                          # Ctrl+1: no longer this tab's key
    assert shown[1].isChecked()
    keys = {sc.key().toString() for sc in tabctl._key_shortcuts}
    assert "Alt+F5" in keys and "Ctrl+1" in keys
    tabctl._open_tab(first)                         # what Alt+F5 does
    assert shown[0].isChecked()
    window.rail.set_open(False)
    window.rail.sync()
    assert shown[0].toolTip().endswith("(Alt+F5)")
    tabctl.set_tab_key(second, "alt+f5")            # one key, one tab
    assert window.cfg.tab_keys == {second: "alt+f5"}
    tabctl.set_tab_key(second, "")                  # removed: no key at all
    assert tabctl.tab_key(second) == ""
    menu = tabctl.tab_menu(shown[1].index)
    assert menu.actions()[-1].text() == "Set hotkey"
    assert tabcontrol.qt_keys("ctrl+shift+num 3").toString() == "Ctrl+Shift+Num+3"
    assert tabcontrol.qt_keys("midi:note 36:LPD8") is None


def test_the_header_version_opens_whats_new_and_stop_all_has_its_own_icon(window, monkeypatch):  # noqa: F811
    from soundboard.ui.setup import whatsnew
    shown = []
    monkeypatch.setattr(whatsnew.WhatsNewDialog, "exec", lambda self: shown.append(self.page))
    window.tagline.clicked.emit()
    assert shown == [""]
    assert not window.stop_btn.icon().isNull()
    from soundboard.ui.kit import icons
    assert "stop_all" in icons.SHAPES and icons.SHAPES["stop_all"] is not icons.SHAPES["stop"]


@pytest.mark.fonts   # loads Segoe UI (conftest runs it last)
def test_an_open_tab_has_room_between_its_icon_and_its_name(qapp):
    """Qt leaves ~4 px there, which looked cramped: the rail adds to it (ICON_PAD)."""
    import os
    from pathlib import Path

    from PySide6.QtGui import QColor, QFontDatabase, QIcon, QPixmap

    from soundboard.ui.kit import theme
    # the app's font: without it (CI has no font folder) the name is drawn as boxes,
    # and the test only passed by counting the open tab's accent edge as the icon
    if (font := Path(os.environ.get("WINDIR", "")) / "Fonts" / "segoeui.ttf").exists():
        QFontDatabase.addApplicationFont(str(font))
    tabs = SideTabs()
    tabs.addTab(QWidget(), "Radio")
    pm = QPixmap(20, 20)
    pm.fill(QColor("#ffffff"))
    tabs.setTabIcon(0, QIcon(pm))
    rail = SideRail(tabs, QWidget(), QLabel(), QLabel(), [], True)
    rail.setStyleSheet(theme.stylesheet())
    rail.show()
    QApplication.processEvents()
    QApplication.processEvents()
    img = rail.buttons[0].grab().toImage()
    bg = img.pixel(img.width() - 3, img.height() // 2) & 0xFFFFFF

    def inked(x):
        return any((img.pixel(x, y) & 0xFFFFFF) != bg and
                   max(abs(((img.pixel(x, y) >> k) & 255) - ((bg >> k) & 255))
                       for k in (0, 8, 16)) > 40 for y in range(4, img.height() - 4))
    cols = [x for x in range(img.width()) if inked(x)]
    first_end = next(x for x, nxt in zip(cols, cols[1:] + [10_000]) if nxt - x > 3)
    words_start = next(x for x in cols if x > first_end)
    assert words_start - first_end >= 9   # (4 px before, ~10 px now)
    rail.close()


def _foot_three(qapp):
    tabs = SideTabs()
    tabs.addTab(QWidget(), "One")
    gear, onion = QPushButton(), QPushButton()
    rail = SideRail(tabs, QWidget(), QLabel(), QLabel(), [], True, [gear, onion])
    rail.resize(rail.width(), 600)
    rail.show()
    QApplication.processEvents()
    return rail, gear, onion


def test_a_button_between_settings_and_the_arrow_sits_exactly_in_the_middle(qapp):
    """Open: Settings at the near side, the arrow at the far one, the one between them
    the same gap from both, on the cards' centre line (Qt's stretch gave one gap the
    odd pixel)."""
    rail, gear, onion = _foot_three(qapp)
    g, o, a = gear.geometry(), onion.geometry(), rail.toggle.geometry()
    assert g.center().y() == o.center().y() == a.center().y()
    assert o.left() - g.right() == a.left() - o.right()
    middle = rail._lay.contentsMargins().left() + rail._inner_width() // 2
    assert o.left() + o.width() // 2 == middle
    rail.close()


def test_the_foot_never_overlaps_at_any_width(qapp):
    """Dragged from open to shut and back: the three never overlap or leave the rail,
    side by side they stay evenly spaced, stacked they stay in one column."""
    from soundboard.ui.window.sidebar import BUTTON_W, OPEN_W, SHUT_W
    rail, gear, onion = _foot_three(qapp)
    for x in [*range(OPEN_W, SHUT_W - 1, -3), SHUT_W, *range(SHUT_W, OPEN_W + 1, 3)]:
        rail.drag_width(x)
        QApplication.processEvents()
        rects = [gear.geometry(), onion.geometry(), rail.toggle.geometry()]
        for i, r in enumerate(rects):
            assert r.left() >= 0 and r.right() < rail.width() - 1, (x, r)
            for s in rects[i + 1:]:
                assert not r.intersects(s), (x, r, s)
        g, o, a = rects
        if g.center().y() == o.center().y():
            assert o.left() - g.right() == a.left() - o.right(), x
        else:
            assert g.center().x() == o.center().x() == a.center().x(), x
            # stacked: centred as the shut rail's column is (its 1 px edge not counted)
            assert g.left() == (rail.width() - 1 - BUTTON_W) // 2, x
    rail.finish_resize()
    rail.close()


def test_the_help_bun_opens_its_menu_and_is_never_left_selected(window):  # noqa: F811
    window.show()
    QApplication.processEvents()
    window.btn_about.click()
    QApplication.processEvents()
    acts = window.about_menu.actions()
    texts = [a.text() for a in acts if a.text()]
    assert texts == ["Join the Discord", "Send feedback", "Report a problem", "Turn into Bun"]
    assert acts[3].isSeparator()   # a line over Turn into Bun
    assert not window.btn_about.isChecked()
    # up from the rail's foot, its edge over Bun's (down, it ran off the window)
    menu, bun = window.about_menu.geometry(), window.btn_about
    top_left = bun.mapToGlobal(bun.rect().topLeft())
    assert menu.bottom() < top_left.y() and menu.left() == top_left.x()
    window.about_menu.hide()
    acts[4].trigger()
    assert window.bunctl.bun_up() and not window.isVisible()
    window.bunctl.leave_bun_mode()


def test_a_small_chevron_has_a_solid_tip(qapp):
    """At 12 px (the sidebar card's ›) the tip fell between two pixel rows and came out
    a dim smudge: its corners are snapped to the pixel grid now."""
    from soundboard.ui.kit import icons
    img = icons.pixmap("fold", 12, "#ffffff").toImage()
    tip_x = max(x for x in range(12) for y in range(12) if img.pixelColor(x, y).alpha() > 40)
    assert max(img.pixelColor(tip_x, y).alpha() for y in range(12)) > 200


def test_settings_showing_draws_its_cog_in_the_accent(window):  # noqa: F811
    """Selected, the cog is the accent on the soft fill, as a selected tab's icon (it was
    on_accent: white, nearly invisible in Light)."""
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QColor, QIcon

    from soundboard.ui.kit import theme
    pm = window.gear.icon().pixmap(QSize(20, 20), QIcon.Normal, QIcon.On)
    img = pm.toImage()
    inked = [img.pixelColor(x, y) for x in range(20) for y in range(20)
             if img.pixelColor(x, y).alpha() > 200]
    assert inked and inked[0].rgb() == QColor(theme.T["accent"]).rgb()


def test_a_tab_switch_doesnt_lay_the_rail_out_again(window, monkeypatch):  # noqa: F811
    """Switching tabs recomputed the audio status and laid the rail's status out again
    (~15 ms of each switch on a slower PC) though nothing on it changed: now only
    Setup (whose hints those are) brings it up to date, and the same words put on a
    status button again change nothing. New words still show."""
    from soundboard.ui.window import sidebar
    from soundboard.ui.window.tabcontrol import TAB_INDEX
    window.resize(1200, 800)
    window.show()
    QApplication.processEvents()
    status, shown = [], []
    real_status, real_show = window.statusctl._update_status, SideRail.show_status
    monkeypatch.setattr(window.statusctl, "_update_status",
                        lambda: status.append(1) or real_status())
    monkeypatch.setattr(SideRail, "show_status",
                        lambda self, w: shown.append(w) or real_show(self, w))
    for key in ("apps", "voice", "store", "sounds"):
        window.tabs.setCurrentIndex(TAB_INDEX[key])
        QApplication.processEvents()
    assert not status and not shown
    window.tabs.setCurrentIndex(TAB_INDEX["setup"])
    QApplication.processEvents()
    assert status and not shown        # the same words: the rail stays as it is
    live = window.btn_air
    text = live.property("railtext")
    sidebar.put(live, "Something new")
    assert shown == [live] and live.accessibleName() == "Something new"
    sidebar.put(live, text)
