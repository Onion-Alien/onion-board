"""ui.responsive.Fitter: what gives way when the window gets small, and comes back
when it grows."""
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from soundboard.ui.window import responsive

LONG = "Your mic in Discord / games: a long device name here"
SHORT = "Connected"


def header(text: str) -> tuple[QWidget, QPushButton]:
    """A window's top row, nested in its page's layout as the main window's is."""
    root = QWidget()
    v = QVBoxLayout(root)
    row = QHBoxLayout()
    v.addLayout(row)
    pill = QPushButton(text)
    row.addWidget(pill)
    row.addWidget(QPushButton("Settings"))
    return root, pill


def test_a_step_that_changes_text_in_a_nested_row_is_measured_fresh(qapp):
    """Growing from narrow, a step that put back a long text deep in a row was judged
    by the row's old (short) size: it stayed back, the window didn't fit, and the
    main window fell into the mini player at a size its full layout fits (first
    640 -> 900 px wide with search results showing)."""
    long_w = header(LONG)[0].minimumSizeHint().width()     # twins, measured apart
    short_w = header(SHORT)[0].minimumSizeHint().width()
    assert short_w < long_w
    root, pill = header(LONG)
    f = responsive.Fitter(root)
    f.add(10, "w", lambda short: pill.setText(SHORT if short else LONG))
    root.show()
    qapp.processEvents()
    for width in (long_w - 1, short_w + 4):     # narrow: the short text
        f.fit(QSize(width, 400))
        assert pill.text() == SHORT
        assert f.need().width() == short_w      # what it's judged by: measured fresh
    mid = (short_w + long_w) // 2               # grown, but not enough for the long one
    f.fit(QSize(mid, 400))
    assert pill.text() == SHORT, "brought back a text that doesn't fit"
    f.fit(QSize(long_w + 10, 400))
    assert pill.text() == LONG
    root.deleteLater()


def test_a_fit_measures_again_only_after_a_step_changed_something(qapp):
    """Each measure finds and invalidates every layout in the window: a resize step
    measured 5-6 times though nothing changed in between."""
    root, pill = header(LONG)
    f = responsive.Fitter(root)
    f.add(10, "w", lambda short: pill.setText(SHORT if short else LONG))
    root.show()
    qapp.processEvents()
    real, measured = root.minimumSizeHint, []
    root.minimumSizeHint = lambda: (measured.append(1), real())[1]
    wide = f.fit(QSize(2000, 400))
    assert len(measured) == 1 and wide == f.need()   # nothing to do: measured once
    measured.clear()
    narrow = f.fit(QSize(10, 400))                   # one step applied: and again after it
    assert pill.text() == SHORT and len(measured) == 2 and narrow.width() < wide.width()
    root.deleteLater()


def test_touch_leaves_no_layout_item_wrappers(qapp):
    """touch() walks every layout above a widget, a QStackedWidget's too. A Python
    wrapper for a layout item is kept by its layout, and removing a stack's page
    (Radio switched off) frees that item behind PySide's back: the next object made at
    its address got the dead wrapper and the app crashed natively (issue #339)."""
    import gc

    from PySide6.QtWidgets import QLabel, QLayout, QLayoutItem, QStackedWidget

    def items():   # the items themselves (a layout is an item too, and is safe)
        gc.collect()
        return sum(isinstance(o, QLayoutItem) and not isinstance(o, QLayout)
                   for o in gc.get_objects())

    root = QWidget()
    v = QVBoxLayout(root)
    stack = QStackedWidget()
    v.addWidget(stack)
    pages = []
    for i in range(3):
        page = QWidget()
        row = QHBoxLayout()
        QVBoxLayout(page).addLayout(row)
        row.addWidget(QLabel(f"page {i}"))
        stack.addWidget(page)
        pages.append(page)
    before = items()
    responsive.touch(pages[1].findChild(QLabel))
    assert items() == before
    stack.removeWidget(pages[1])
    pages[1].deleteLater()
    root.deleteLater()


def test_touch_still_reaches_nested_rows(qapp):
    """Each nested row caches its own size: touch() marks them all stale."""
    root, pill = header(LONG)
    rows = root.layout().findChildren(QHBoxLayout)
    hit = []
    for row in rows:
        row.invalidate = lambda r=row: hit.append(r)
    responsive.touch(pill)
    assert rows and all(r in hit for r in rows)
    root.deleteLater()


def test_fit_preserves_an_outer_paint_transaction(qapp):
    root, pill = header(LONG)
    fitter = responsive.Fitter(root)
    fitter.add(10, "w", responsive.icon_only(pill))
    root.setUpdatesEnabled(False)
    fitter.fit(QSize(100, 400))
    assert not root.updatesEnabled()
    root.setUpdatesEnabled(True)
    root.deleteLater()


def test_nested_update_hold_commits_geometry_before_resuming(qapp):
    root, pill = header(LONG)
    root.show()
    qapp.processEvents()
    with responsive.hold_updates(root):
        root.resize(800, 300)
        with responsive.hold_updates(root):
            pill.hide()
        assert not root.updatesEnabled()
    assert root.updatesEnabled()
    assert pill.isHidden()
    root.deleteLater()


class _Tall(QWidget):
    """A page whose height follows its width, counting how often it's asked."""

    def __init__(self, per_px: float):
        super().__init__()
        self.per_px, self.asked = per_px, 0

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        self.asked += 1
        return int(w * self.per_px)


def test_only_the_page_on_show_says_how_tall_it_is(qapp):
    """Dragging the window's edge: Qt's stacks and tab widget ask every page how tall
    it is at the new width, and the hidden tabs' wrapped text was laid out again on
    every step (~10 frames a second on the Radio, Triggers and Voice tabs)."""
    from soundboard.ui.kit.panel import ShownStack
    from soundboard.ui.window.sidebar import SideTabs
    for make, add, show in ((ShownStack, ShownStack.addWidget, ShownStack.setCurrentWidget),
                            (SideTabs, lambda t, p: t.addTab(p, ""), SideTabs.setCurrentWidget)):
        holder = make()
        shown, hidden = _Tall(0.5), _Tall(2.0)
        add(holder, shown)
        add(holder, hidden)
        show(holder, shown)
        shown.asked = hidden.asked = 0   # (Qt asks while they're added)
        h = holder.heightForWidth(400)
        assert hidden.asked == 0 and shown.asked == 1
        assert 200 <= h < 800   # the shown page's height (and a tab widget's own frame)
        show(holder, hidden)
        assert holder.heightForWidth(400) > 2 * h   # the other page, once it shows


def two_rows() -> tuple[QWidget, QPushButton, list[QPushButton]]:
    """A wide row (the part that decides the width) over a row of small buttons."""
    root = QWidget()
    v = QVBoxLayout(root)
    wide = QPushButton("wide")
    wide.setMinimumWidth(600)
    v.addWidget(wide)
    row = QHBoxLayout()
    v.addLayout(row)
    small = []
    for name in ("a", "b"):
        b = QPushButton(name)
        b.setMinimumWidth(100)
        row.addWidget(b)
        small.append(b)
    return root, wide, small


def test_steps_that_did_not_help_come_back(qapp):
    """Steps go lowest first until it fits: the ones before the step that fixed it may
    not have narrowed the widest part at all. At 1100 px the levels strip was it, and
    15 controls (the speed button, the radio's volume, Say's Stop) were hidden for
    nothing until the window grew past the size they went at."""
    root, wide, small = two_rows()
    f = responsive.Fitter(root)
    f.add(10, "w", responsive.hide(small[0]))
    f.add(20, "w", responsive.hide(small[1]))
    f.add(50, "w", responsive.hide(wide))
    root.show()
    qapp.processEvents()
    f.fit(QSize(400, 400))
    assert wide.isHidden()
    assert not small[0].isHidden() and not small[1].isHidden(), "hid what didn't help"
    assert f.compact_count() == 1
    root.deleteLater()


def test_growing_brings_back_whatever_fits(qapp):
    """Growing, the last-hidden step not fitting yet mustn't keep the earlier ones in
    another row hidden (the radio's volume stayed hidden from 800 back to 1180 px)."""
    root, wide, small = two_rows()
    f = responsive.Fitter(root)
    f.add(10, "w", responsive.hide(small[0]))
    f.add(20, "w", responsive.hide(small[1]))
    f.add(50, "w", responsive.hide(wide))
    root.show()
    qapp.processEvents()
    f.fit(QSize(20, 400))                  # too small for anything: all three go
    assert wide.isHidden() and small[0].isHidden() and small[1].isHidden()
    f.fit(QSize(400, 400))
    assert wide.isHidden()                 # still doesn't fit
    assert not small[0].isHidden() and not small[1].isHidden()
    f.fit(QSize(800, 400))
    assert not wide.isHidden()
    assert f.compact_count() == 0
    root.deleteLater()


def test_growing_keeps_the_more_important_step_shown(qapp):
    """Growing, a later (more important) step comes back first, hiding earlier ones
    to make room if it has to: giving the room to them instead kept the levels strip
    in its one-group form at 1700 px."""
    root = QWidget()
    row = QHBoxLayout(root)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(0)
    big = QPushButton("big")
    big.setMinimumWidth(300)
    row.addWidget(big)
    small = []
    for name in ("a", "b"):
        b = QPushButton(name)
        b.setMinimumWidth(100)
        row.addWidget(b)
        small.append(b)
    f = responsive.Fitter(root)
    f.add(10, "w", responsive.hide(small[0]))
    f.add(20, "w", responsive.hide(small[1]))
    f.add(50, "w", responsive.hide(big))
    root.show()
    qapp.processEvents()
    f.fit(QSize(250, 400))                 # big goes; a and b fit beside nothing
    assert big.isHidden() and not small[0].isHidden() and not small[1].isHidden()
    f.fit(QSize(450, 400))                 # big and one of them
    assert not big.isHidden(), "the room went to the less important ones"
    assert small[0].isHidden() and not small[1].isHidden()
    f.fit(QSize(900, 400))
    assert f.compact_count() == 0 and not small[0].isHidden()
    root.deleteLater()
