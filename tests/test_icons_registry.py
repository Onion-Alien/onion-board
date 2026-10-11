"""The live-retheme registry in soundboard.ui.icons lets deleted widgets go."""
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QLabel, QTabWidget, QWidget

from soundboard.ui import icons


def test_live_badge_draws_at_requested_screen_resolution(qapp):
    from PySide6.QtCore import QSize, Qt
    from PySide6.QtGui import QIcon, QPixmap
    from soundboard import theme

    requests = []

    def draw(px, mode, state):
        requests.append((px, mode, state))
        pm = QPixmap(px, px)
        pm.fill(Qt.GlobalColor.transparent)
        return pm

    badge = icons._with_badge(icons.sharp_icon(draw))
    for ratio in (1.0, 1.25, 1.5, 2.0):
        for mode in (QIcon.Mode.Normal, QIcon.Mode.Disabled, QIcon.Mode.Selected):
            for state in (QIcon.State.Off, QIcon.State.On):
                physical = round(18 * ratio)
                pm = badge.pixmap(QSize(18, 18), ratio, mode, state)
                assert (physical, mode, state) in requests
                assert pm.width() == physical
                # Qt adjusts fractional ratios to account for pixel rounding.
                assert abs(pm.deviceIndependentSize().width() - 18) <= 1
                dot = pm.toImage().pixelColor(round(physical * 0.8), round(physical * 0.2))
                assert dot.name() == theme.T['live_text']


def test_registry_drops_deleted_labels_and_tab_widgets(qapp):
    """A dialog's labels and Settings' tabs went on the list each time it opened
    (6 -> 66 entries in a churn test)."""
    def churn():
        box = QWidget()
        label = QLabel(box)
        tabs = QTabWidget(box)
        for i in range(3):
            tabs.addTab(QWidget(), str(i))
            icons.set_tab_icon(tabs, i, "settings")
        icons.set_label_icon(label, "settings")
        icons.set_label_icon(label, "settings")         # again: still one entry for it
        box.deleteLater()
        qapp.sendPostedEvents(None, QEvent.DeferredDelete)

    churn()
    labels, tabs = len(icons._labels), len(icons._tabs)
    for _ in range(10):
        churn()
    assert len(icons._labels) <= labels and len(icons._tabs) <= tabs
