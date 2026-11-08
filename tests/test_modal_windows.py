"""Card windows on the shared frame (kit/modalframe.py): solid when opened from inside a
page card, no click passed through, no title bar over the card's own, a shadow that fades
out inside its window, and toasts on the panel."""
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QDialog, QFrame, QPushButton, QVBoxLayout, QWidget

from soundboard.ui.kit import modalframe, theme
from soundboard.ui.kit.modalframe import InfoCard, ModalDialog, ModalFrame


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
        g, win = card.geometry(), w.frameGeometry()
        assert win.left() <= g.left() and g.right() <= win.right()
        assert card.width() >= modalframe.NARROWEST
        card.close()
    finally:
        w.close()
