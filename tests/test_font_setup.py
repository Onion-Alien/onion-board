"""The setup mix diagram's icon and capital ink share a line in every font."""
import pytest
from PySide6.QtWidgets import QApplication, QLabel
from test_mainwindow import window  # noqa: F401
from test_font_footer import ink_middle
from soundboard.ui.mainwindow import TAB_INDEX


@pytest.mark.parametrize("name", ["Dark", "Amber Terminal", "Comic Sans"])
def test_setup_flow_icon_matches_capital(window, name):  # noqa: F811
    window.apply_theme(name)
    window.cfg.route = "cable"
    window._show_route()
    window.show()
    window.resize(1700, 900)
    window.tabs.setCurrentIndex(TAB_INDEX["setup"])
    for _ in range(8):
        QApplication.processEvents()
        window._refit()
    label = window.flow_snd
    host = window.mic_flow
    icons = [w for w in host.findChildren(QLabel) if not w.pixmap().isNull()]
    icon = min(icons, key=lambda mark: abs(ink_middle(mark, host)
                                         - ink_middle(label, host, capital=True)))
    assert abs(ink_middle(icon, host) - ink_middle(label, host, capital=True)) <= 1
