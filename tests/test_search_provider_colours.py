from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon

from soundboard.ui.kit import theme
from soundboard.ui.kit import icons
from soundboard.ui.sounds.ytsearch import SearchResults


def test_provider_menu_icons_follow_theme_changes(qapp):
    original = theme.current_name
    results = SearchResults()
    try:
        for name in ("Dark", "Hacker", "Light"):
            theme.set_current(name)
            icons.retheme()
            for key, action in results.site_actions.items():
                expected = icons.icon(key, "accent", "accent")
                for mode in (QIcon.Normal, QIcon.Selected, QIcon.Disabled):
                    for state in (QIcon.Off, QIcon.On):
                        assert action.icon().pixmap(QSize(18, 18), mode, state).toImage() == (
                            expected.pixmap(QSize(18, 18), mode, state).toImage())
    finally:
        results.deleteLater()
        theme.set_current(original)
        icons.retheme()
