"""Temporary (issue #339): one thing at a time, many times, to find what crashes."""
from soundboard.settings import SettingsDialog
from test_mainwindow import window as main_window  # noqa: F401


def _cycle(w, key):
    w.set_tab_on(key, False)
    w.set_tab_on(key, True)


def test_v_none(main_window):  # noqa: F811
    pass


def test_v_settings(main_window):  # noqa: F811
    d = SettingsDialog(main_window, "tabs")
    d.close()
    d.deleteLater()


def test_v_voice(main_window):  # noqa: F811
    _cycle(main_window, "voice")


def test_v_radio(main_window):  # noqa: F811
    _cycle(main_window, "radio")


def test_v_apps(main_window):  # noqa: F811
    _cycle(main_window, "apps")


def test_v_triggers(main_window):  # noqa: F811
    _cycle(main_window, "triggers")
