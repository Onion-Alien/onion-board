"""Layout checks any UI test can call on a real widget (DESIGN.md section 2, *Breathing
room*). They catch what keeps slipping into pictures: a list's rows hard against its
scroll bar, a control touching its card's edge."""
from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QApplication, QFrame, QScrollArea, QWidget

CARD_EDGE = 12   # nothing in a card nearer its edge than this (cards use 14-18)
LIST_GAP = 8     # between a scrolling list's items and its scroll bar


def _shown(w: QWidget, root: QWidget) -> bool:
    return w.isVisibleTo(root) and w.width() > 0 and w.height() > 0


def breathing_room(root: QWidget, edge: int = CARD_EDGE, gap: int = LIST_GAP) -> list[str]:
    """What breaks the rule under `root` (itself included), as readable lines:
    a card's own pieces nearer its edge than `edge`, and a scrolling list's items
    nearer its visible scroll bar than `gap`. Empty when it all has room."""
    for _ in range(3):   # pending layouts and resizes first: they show the scroll bars
        QApplication.processEvents()
    bad = []
    cards = [root] if root.objectName() == "card" else []
    cards += [c for c in root.findChildren(QFrame, "card") if _shown(c, root)]
    for card in cards:
        inside = card.rect().adjusted(edge, edge, -edge, -edge)
        for w in card.findChildren(QWidget):
            if w.parentWidget() is not card or not _shown(w, root):
                continue
            r = QRect(w.mapTo(card, QPoint(0, 0)), w.size())
            if not inside.contains(r):
                bad.append(f"{type(w).__name__} {w.objectName()!r} at {r.getRect()} is nearer "
                           f"than {edge} px to its card's edge ({card.rect().getRect()})")
    for area in root.findChildren(QScrollArea):
        bar = area.verticalScrollBar()
        body = area.widget()
        if body is None or not _shown(area, root) or not bar.isVisible():
            continue
        bar_x = bar.mapTo(area, QPoint(0, 0)).x()
        for w in body.findChildren(QWidget):
            if w.parentWidget() is not body or not _shown(w, root):
                continue
            right = w.mapTo(area, QPoint(w.width(), 0)).x()
            if right > bar_x - gap:
                bad.append(f"{type(w).__name__} {w.objectName()!r} ends at x={right}, "
                           f"{bar_x - right} px from the scroll bar (needs {gap})")
    return bad


def assert_breathing_room(root: QWidget, edge: int = CARD_EDGE, gap: int = LIST_GAP):
    bad = breathing_room(root, edge, gap)
    assert not bad, "\n".join(bad)
