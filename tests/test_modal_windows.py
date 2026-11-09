"""Card windows on the shared frame (kit/modalframe.py): solid when opened from inside a
page card, no click passed through, no title bar over the card's own, a shadow that fades
out inside its window, and toasts on the panel."""
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication, QDialog, QFrame, QPushButton, QVBoxLayout, QWidget

from soundboard.ui.kit import modalframe, theme
from soundboard.ui.kit.modalframe import InfoCard, ModalDialog, ModalFrame
from test_mainwindow import window  # noqa: F401


def _page_card(qapp):
    """A window with a page card (`QFrame#card`) and a button inside it."""
    theme.apply(qapp, "Dark")
    w = QWidget()
    w.resize(900, 700)
    card = QFrame(w)
    card.setObjectName("card")
    QVBoxLayout(card)
    btn = QPushButton("i", card)
    card.layout().addWidget(btn)
    card.setGeometry(20, 20, 400, 200)
    w.show()
    qapp.processEvents()
    return w, btn


def _alpha(win: QWidget, at: QPoint) -> int:
    return win.grab().toImage().pixelColor(at).alpha()


def test_a_card_opened_inside_a_page_card_is_solid(qapp):
    w, btn = _page_card(qapp)
    try:
        card = InfoCard("Sound modes", points=[("info", "Game", "Words")], parent=btn)
        assert card.parentWidget() is w   # its window's, not the page card's
        card.show()
        qapp.processEvents()
        f = card.frame.geometry()
        assert _alpha(card, QPoint(f.center().x(), f.top() + 30)) == 255
        box = ModalDialog(btn, "Copy a built-in mode")
        box.frame.add_text("Start from")
        assert box.parentWidget() is w
        box.show()
        qapp.processEvents()
        g = box.frame.geometry()
        assert _alpha(box, QPoint(g.center().x(), g.top() + 30)) == 255
        box.close()
        card.close()
    finally:
        w.close()


def test_a_click_outside_a_pop_up_card_goes_no_further(qapp):
    card = InfoCard("Effects")
    # Qt hands a click that closes a pop-up on to what's under it (the voice tile
    # under the Effects card got picked); and Windows' square pop-up shadow is off
    assert card.testAttribute(Qt.WidgetAttribute.WA_NoMouseReplay)
    assert card.windowFlags() & Qt.WindowType.NoDropShadowWindowHint


def test_the_feedback_box_blocks_the_page_behind_it(qapp, monkeypatch):
    from soundboard.ui.kit import feedbackdialog
    from types import SimpleNamespace
    w = QWidget()
    w.show()
    try:
        dlg = feedbackdialog.FeedbackDialog(SimpleNamespace(usage=False), w)
        assert dlg.windowModality() != Qt.WindowModality.NonModal
        assert dlg.KEEP_OPEN   # and a click outside doesn't throw what's ticked away
        dlg.close()
    finally:
        w.close()


def test_a_dialog_on_the_frame_has_no_title_bar_over_the_cards(qapp):
    w, btn = _page_card(qapp)
    try:
        dlg = QDialog(btn)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(0, 0, 0, 0)
        frame = ModalFrame("Custom modes", close=False, docked=True)
        lay.addWidget(frame)
        assert dlg.windowFlags() & Qt.WindowType.FramelessWindowHint
        assert dlg.parentWidget() is w   # (not the page card's: see-through)
        assert frame.property("docked") is False   # its own edge and corners
        assert not frame.close_btn.isHidden()   # the window's ✕ is gone: the card's closes
        dlg.setMinimumWidth(620)   # the card's width, as its code sets it
        dlg.show()
        qapp.processEvents()
        assert dlg.isVisible()
        assert frame.width() >= 620   # the shadow's room came on top
        frame.close_btn.click()
        qapp.processEvents()
        assert not dlg.isVisible()
    finally:
        w.close()


def test_a_dialog_with_more_than_the_frame_keeps_its_title_bar(qapp):
    dlg = QDialog()
    lay = QVBoxLayout(dlg)
    lay.addWidget(QPushButton("first"))
    lay.addWidget(ModalFrame("A part of it"))
    assert not dlg.windowFlags() & Qt.WindowType.FramelessWindowHint


def test_the_shadow_fades_out_inside_its_window(qapp):
    for name in ("Dark", "Light"):
        theme.apply(qapp, name)
        card = InfoCard("Title", points=[("info", "A", "B")])
        card.show()
        qapp.processEvents()
        img = card.grab().toImage()
        f = card.frame.geometry()
        edges = [img.pixelColor(card.width() - 1, f.center().y()).alpha(),
                 img.pixelColor(f.center().x(), card.height() - 1).alpha(),
                 img.pixelColor(f.center().x(), 0).alpha(),
                 img.pixelColor(0, f.center().y()).alpha()]
        assert max(edges) <= 3, (name, edges)   # no hard square edge round the card
        card.close()


def test_a_toast_in_a_card_window_stays_on_its_panel(qapp):
    from soundboard.ui.kit import busy
    theme.apply(qapp, "Dark")
    dlg = QDialog()
    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(0, 0, 0, 0)
    frame = ModalFrame("Custom modes")
    lay.addWidget(frame)
    frame.add_text("words " * 40)
    dlg.resize(600, 400)
    dlg.show()
    qapp.processEvents()
    t = busy.toast(dlg, "Removed it", "", 5000)
    qapp.processEvents()
    assert t is not None
    panel = frame.geometry()
    assert panel.contains(t.geometry().adjusted(8, 8, -8, -8)), (panel, t.geometry())
    dlg.close()


def test_a_card_is_kept_inside_a_narrow_window(qapp):
    w = QWidget()
    w.move(100, 100)
    w.resize(460, 700)
    w.show()
    qapp.processEvents()
    try:
        card = InfoCard("Sound modes", points=[("info", "Game", "Words " * 30)], width=520,
                        parent=w)
        card.place_at(w.x() + 300, w.y() + 40)
        panel = card.frame.geometry().translated(card.pos())   # (its shadow may reach out)
        assert w.geometry().contains(panel), (panel, w.geometry())
        assert card.frame.width() >= modalframe.NARROWEST
        card.close()
    finally:
        w.close()


def test_a_window_can_say_where_its_toasts_go(qapp):
    """Custom modes puts its Undo bar in the Close row (toast_area): no form row under it."""
    from PySide6.QtCore import QRect
    from soundboard.ui.kit import busy

    class Host(QDialog):
        def toast_area(self):
            return QRect(10, 300, 400, 60)

    theme.apply(qapp, "Dark")
    dlg = Host()
    dlg.resize(600, 400)
    dlg.show()
    qapp.processEvents()
    t = busy.toast(dlg, "Removed it", "", 5000)
    qapp.processEvents()
    assert t is not None
    assert QRect(10, 300, 400, 60).contains(t.geometry().adjusted(8, 8, -8, -8)), t.geometry()
    dlg.close()


def test_a_click_that_shuts_the_effects_card_picks_no_voice(qapp, monkeypatch):
    """Windows' order: the press outside shuts the pop-up first, then Qt hands that press
    (and its release) on to the voice tile under it. The tile must not get it: it picked
    another voice and the effect just added (rain) was gone."""
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtTest import QTest
    from tests.test_backdrop import _voice_panel
    p = _voice_panel(monkeypatch)
    try:
        p.resize(1100, 820)
        p.show()
        qapp.processEvents()
        fx = p.fx
        fx.pick("Robot")
        fx.btn_effects.click()
        pop = fx.effects_pop
        fx.set_on_top("rain", 0.5)
        qapp.processEvents()
        assert pop.isVisible()
        name, tile = next((n, b) for n, b in fx._tile.items()
                          if b.isVisible() and n != "Robot")
        spot = tile.rect().center()
        at = tile.mapTo(p, spot)
        # the press: Qt shuts the pop-up on it (the button is down while it hides) ...
        QTest.mousePress(p.windowHandle(), Qt.MouseButton.LeftButton, pos=at)
        qapp.processEvents()
        if pop.isVisible():   # (offscreen Qt hands the press to the pop-up instead)
            pop.close()
        assert not pop.isVisible()
        # ... then hands that press and its release on to what's under it, as on Windows
        for kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
            pt = QPointF(spot)
            down = Qt.MouseButton.LeftButton if kind == QEvent.Type.MouseButtonPress else \
                Qt.MouseButton.NoButton
            ev = QMouseEvent(kind, pt, pt, QPointF(tile.mapToGlobal(spot)),
                             Qt.MouseButton.LeftButton, down, Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(tile, ev)
        QTest.mouseRelease(p.windowHandle(), Qt.MouseButton.LeftButton, pos=at)
        qapp.processEvents()
        assert fx.preset == "Robot", f"the click went on to {name}"
        assert fx.on_top_state()["layers"].get("rain") == 0.5   # what was added stays
        # and the next click is a click again
        tile.click()
        assert fx.preset == name
    finally:
        modalframe._eat_click.disarm()
        p.hide()
        p.shutdown()
        p.deleteLater()


def test_a_card_window_is_as_tall_as_its_words(window):  # noqa: F811
    """No empty band under the title: the shadow's room isn't added twice (Reset, Restore
    points)."""
    from soundboard.ui.kit import fit
    from soundboard.ui.settings.resetguide import ResetGuide, RestorePoints
    for make in (ResetGuide, RestorePoints):
        g = make(window)
        g.show()
        QApplication.processEvents()
        assert g.height() <= fit.needed_height(g, g.width()) + 4, make.__name__
        g.close()


def test_a_card_window_stays_inside_a_small_window(qapp):
    """A short window: the guide is taller than the window's inside. It stays inside
    (it covered the window's title bar) and its words scroll."""
    from soundboard.ui.setup.chatguide import GameGuide
    w = QWidget()
    w.setGeometry(0, 30, 1024, 450)
    w.show()
    qapp.processEvents()
    try:
        g = GameGuide(w, w, "CABLE Output (VB-Audio Virtual Cable)")
        g.show()
        qapp.processEvents()
        from PySide6.QtCore import QMargins
        from soundboard.ui.kit import fit
        room = w.geometry().marginsAdded(QMargins(*modalframe.ROOM_PAD))   # (+ its shadow)
        assert room.contains(g.geometry()), (g.geometry(), w.geometry())
        frame = g.findChild(ModalFrame)
        assert frame.body_scroll is not None   # too tall for it: its body scrolls,
        assert frame.close_btn.isVisible()     # the header and the buttons stay
        assert g.property(fit.SCROLLS)
        g.close()
    finally:
        w.close()


def test_custom_modes_stays_below_the_title_bar_of_a_short_window(window):  # noqa: F811
    """520x530 inside: too tall for it, Custom modes scrolls and stays inside, below the
    window's title bar (it went to the screen's top and covered it)."""
    from soundboard.ui.setup.destpanel import CustomDestDialog
    window.setGeometry(8, 38, 520, 530)
    window.show()
    QApplication.processEvents()
    d = CustomDestDialog(window, window.dest_panel)
    d.show()
    for _ in range(6):
        QApplication.processEvents()
    try:
        panel = d.findChild(ModalFrame)
        top = panel.mapToGlobal(QPoint(0, 0)).y()
        assert top >= window.geometry().top(), (top, window.geometry())
        assert panel.body_scroll is not None
        bottom = top + panel.height()
        assert bottom <= window.geometry().bottom() + 1, (bottom, window.geometry())
    finally:
        d.close()


def test_the_effects_card_has_its_height_before_it_shows(qapp, monkeypatch):
    """Grown right after it showed, the see-through card had Windows refuse an update
    ("UpdateLayeredWindowIndirect failed ... The parameter is incorrect"), every open."""
    from PySide6.QtCore import QEvent, QObject
    from tests.test_backdrop import _voice_panel

    class Count(QObject):
        shown = False
        late = 0

        def eventFilter(self, obj, ev):   # noqa: N802 - Qt API
            if ev.type() == QEvent.Type.Show:
                self.shown = True
            elif ev.type() == QEvent.Type.Resize and self.shown:
                self.late += 1
            return False

    p = _voice_panel(monkeypatch)
    try:
        p.resize(1100, 800)
        p.show()
        qapp.processEvents()
        fx = p.fx
        fx.pick("Robot")
        fx.btn_effects.click()   # (made on the first open)
        fx.effects_pop.close()
        qapp.processEvents()
        c = Count()
        fx.effects_pop.installEventFilter(c)
        fx.btn_effects.click()
        for _ in range(6):
            qapp.processEvents()
        assert c.shown and c.late == 0
        fx.effects_pop.close()
    finally:
        p.hide()
        p.shutdown()
        p.deleteLater()
