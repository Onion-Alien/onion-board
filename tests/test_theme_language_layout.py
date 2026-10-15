"""Translated labels fit the complete screen when each built-in theme is applied."""
import re

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel
from test_mainwindow import window as main_window  # noqa: F401

from soundboard import i18n, theme
from soundboard.ui.appspanel import ElidedLabel


@pytest.fixture(params=["en", "de", "ar", "zh-CN"])
def language(qapp, request):
    direction = qapp.layoutDirection()
    i18n.set_language(request.param)
    qapp.setLayoutDirection(Qt.LayoutDirection.RightToLeft if i18n.is_rtl(request.param)
                           else Qt.LayoutDirection.LeftToRight)
    yield request.param
    i18n.set_language("en")
    qapp.setLayoutDirection(direction)


# What a theme changes besides colour: its stylesheet with every colour, gradient and
# picture taken out. Themes that only recolour lay out the same, so one of each kind
# is enough (5 instead of 32: checking them all took a test shard past CI's limit).
_COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)|url\([^)]*\)"
                     r"|q(?:linear|radial)gradient\([^)]*\)|\b(?:transparent|black|white)\b")


def layout_themes() -> list[str]:
    seen: dict[str, str] = {}
    for name in theme.THEMES:
        seen.setdefault(_COLOUR.sub("C", theme.stylesheet(name)), name)
    return list(seen.values())


@pytest.fixture
def translated_window(language, main_window):  # noqa: F811
    return main_window


def test_translated_labels_fit_across_themes(translated_window):
    w = translated_window
    w.show()
    for name in layout_themes():
        w.themectl.apply_theme(name)
        for width, height in ((800, 600), (440, 600)):
            w.resize(width, height)
            for page in (w.sounds_page, w.setup_page, w.voice, None):
                if page is None:
                    w.setctl.open_settings("appearance")
                else:
                    w.setctl.close_settings()
                    w.tabs.setCurrentWidget(page)
                QApplication.processEvents()
                for label in w.findChildren(QLabel, "pickedname"):
                    if label.isVisibleTo(w):
                        assert label.heightForWidth(label.width()) <= label.height(), (
                            name, width, label.text(), label.height())
                for label in w.findChildren(QLabel):
                    # The transport intentionally elides names in its paintEvent;
                    # QLabel.text() keeps the complete value for its tooltip.
                    if (isinstance(label, ElidedLabel) or not label.isVisibleTo(w)
                            or not label.text() or label.wordWrap()
                            or "<" in label.text()):
                        continue
                    rect = label.contentsRect().adjusted(label.margin(), label.margin(),
                                                        -label.margin(), -label.margin())
                    fm = label.fontMetrics()
                    assert fm.horizontalAdvance(label.text()) <= rect.width(), (
                        name, width, label.objectName(), label.text(), rect.width())
                    assert fm.height() <= rect.height(), (
                        name, width, label.objectName(), label.text(), rect.height())
