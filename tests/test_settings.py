"""The Settings window's layout: pages scroll instead of squashing their rows."""
from PySide6.QtWidgets import QLabel, QPushButton, QScrollArea

from soundboard.settings import SettingsDialog
from soundboard.ui import busy
from test_mainwindow import window  # noqa: F401  (the real MainWindow fixture)


def test_a_short_window_scrolls_a_page_instead_of_squashing_it(window, qapp):  # noqa: F811
    d = SettingsDialog(window, "hotkeys")
    d.show()
    d.resize(2000, 700)             # wide and short, like a maximized window on a small screen
    for _ in range(5):
        qapp.processEvents()
    sa = d.tabs.currentWidget()
    assert isinstance(sa, QScrollArea)
    page = sa.widget()
    assert page.height() > sa.viewport().height()          # it scrolls
    for wdg in page.findChildren(QLabel) + page.findChildren(QPushButton):
        if wdg.isVisibleTo(page) and wdg.text():
            want = wdg.heightForWidth(wdg.width()) if wdg.hasHeightForWidth() else -1
            assert wdg.height() >= max(want, wdg.minimumSizeHint().height()), wdg.text()
    d.close()


def test_support_opens_the_project_page_not_an_address_in_the_app(window, monkeypatch):  # noqa: F811
    from soundboard import settings
    opened = []
    monkeypatch.setattr(busy.QDesktopServices, "openUrl", lambda u: opened.append(u.toString()))
    d = SettingsDialog(window, "general")
    btn = next(b for b in d.findChildren(QPushButton) if "Support" in b.text())
    btn.click()
    assert opened == ["https://github.com/Onion-Alien/onion-board#support-onion-board"]
    d.close()


def test_each_page_opens_by_name_and_holds_its_cards(window):  # noqa: F811
    where = {"audio": ("DEVICES", "YOUR MIC", "WHO'S LISTENING", "AUDIO BUFFERING"),
             "hotkeys": ("HOTKEY SOUNDS",),
             "general": ("WINDOW", "RUNNING IN THE BACKGROUND", "BACKUP", "ADD-ONS",
                         "FEEDBACK AND PROBLEMS",
                         "SUPPORT ONION BOARD"),
             "updates": ("APP UPDATES", "DOWNLOADER (YT-DLP)"),
             "remote": ("REMOTE CONTROL (STREAM DECK, SCRIPTS)",)}
    for page, titles in where.items():
        d = SettingsDialog(window, page)
        shown = {lb.text() for lb in d.tabs.currentWidget().widget().findChildren(QLabel)}
        assert set(titles) <= shown, page
        d.close()
    d = SettingsDialog(window, "nonsense")
    assert d.tabs.currentIndex() == 0
    d.close()


def test_audio_page_picks_input_and_output_through_the_window(window, monkeypatch):  # noqa: F811
    window._fill_combo(window.cb_mic, ["Mic A", "Headset Mic"], "Mic A")
    window._fill_combo(window.cb_mon, ["Speakers", "Headset"], "Speakers")
    picked = []
    monkeypatch.setattr(window, "on_device",
                        lambda cb, attr: picked.append((attr, cb.currentData())))
    d = SettingsDialog(window, "audio")
    mic, mon = d.dev_combos[0][0], d.dev_combos[1][0]
    assert [mic.itemText(i) for i in range(mic.count())] == ["— none —", "Mic A", "Headset Mic"]
    assert mon.currentText() == "Speakers"
    mic.activated.emit(2)
    mon.activated.emit(2)
    assert picked == [("mic_device", "Headset Mic"), ("mon_device", "Headset")]
    assert window.cb_mon.currentText() == "Headset"   # the Setup tab follows
    d.close()


def test_feedback_and_problem_buttons_only_open_the_browser(window, monkeypatch):  # noqa: F811
    from soundboard import __version__, feedback, settings
    opened = []
    monkeypatch.setattr(busy.QDesktopServices, "openUrl", lambda u: opened.append(u.toString()))
    d = SettingsDialog(window, "general")
    monkeypatch.setattr(feedback, "FORM_URL", "https://forms.example.com/r/x")
    d.feedback_btn.click()
    d.problem_btn.click()
    assert opened[0] == f"https://forms.example.com/r/x?version={__version__}"
    assert opened[1].startswith("https://github.com/Onion-Alien/onion-board/issues/new?labels=bug")
    assert __version__ in opened[1]
    monkeypatch.setattr(feedback, "FORM_URL", "")       # no form: feedback goes to GitHub too
    d.feedback_btn.click()
    assert opened[2] == opened[1]
    d.close()


def test_onion_watch_can_be_removed_from_settings(window, monkeypatch):  # noqa: F811
    from types import SimpleNamespace

    from soundboard import watchaddon
    tab = window.triggers
    d = SettingsDialog(window, "general")
    assert not d.addon_remove.isVisibleTo(d) and "isn't installed" in d.addon_label.text()
    d.close()
    monkeypatch.setattr(tab, "info", SimpleNamespace(version="9.9"))
    monkeypatch.setattr(watchaddon, "removable", lambda info, base: True)
    removed = []

    def fake_remove():
        removed.append(True)
        tab.info = None
    monkeypatch.setattr(tab, "remove", fake_remove)
    d = SettingsDialog(window, "general")
    assert d.addon_remove.isVisibleTo(d) and "9.9 is installed" in d.addon_label.text()
    d.addon_remove.click()
    assert removed and not d.addon_remove.isVisibleTo(d)
    d.close()
