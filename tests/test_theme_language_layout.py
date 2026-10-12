"""Translated labels fit the complete screen when each built-in theme is applied."""
import pytest
from PySide6.QtWidgets import QApplication, QLabel
from test_mainwindow import window as main_window  # noqa: F401

from soundboard import i18n, theme


@pytest.fixture(params=["en", "de", "ar", "zh-CN"])
def language(request):
    i18n.set_language(request.param)
    yield request.param
    i18n.set_language("en")


@pytest.fixture
def translated_window(language, main_window):  # noqa: F811
    return main_window


def test_translated_labels_fit_across_themes(translated_window):
    w = translated_window
    w.show()
    for name in theme.THEMES:
        w.apply_theme(name)
        for width, height in ((800, 600), (440, 600)):
            w.resize(width, height)
            for page in (w.sounds_page, w.setup_page, w.voice, None):
                if page is None:
                    w.open_settings("appearance")
                else:
                    w.close_settings()
                    w.tabs.setCurrentWidget(page)
                QApplication.processEvents()
                for label in w.findChildren(QLabel, "pickedname"):
                    if label.isVisibleTo(w):
                        assert label.heightForWidth(label.width()) <= label.height(), (
                            name, width, label.text(), label.height())
                for label in w.findChildren(QLabel):
                    if (not label.isVisibleTo(w) or not label.text() or label.wordWrap()
                            or "<" in label.text()):
                        continue
                    rect = label.contentsRect().adjusted(label.margin(), label.margin(),
                                                        -label.margin(), -label.margin())
                    fm = label.fontMetrics()
                    assert fm.horizontalAdvance(label.text()) <= rect.width(), (
                        name, width, label.objectName(), label.text(), rect.width())
                    assert fm.height() <= rect.height(), (
                        name, width, label.objectName(), label.text(), rect.height())
