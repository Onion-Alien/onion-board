"""Add-on installs the app was closed in the middle of: the marks
(soundboard/addons/addonmarks.py) and the bar that offers them again at the next start
(ui/window/addonnotice.py). Nothing is downloaded or installed."""
import pytest
from conftest import process_events

from soundboard.addons import addonmarks
from test_mainwindow import window  # noqa: F401  (the real MainWindow fixture)


def test_a_mark_is_there_only_while_the_install_runs(app_dir):
    seen = []
    with addonmarks.running(addonmarks.AI_VOICES):
        seen = addonmarks.cut_off()
    assert seen == [addonmarks.AI_VOICES] and addonmarks.cut_off() == []


def test_a_failed_install_leaves_no_mark(app_dir):
    def fails():
        raise OSError("disk full")
    with pytest.raises(OSError):
        addonmarks.marked(addonmarks.WATCH, fails)()
    assert addonmarks.cut_off() == []


def test_a_mark_the_app_never_cleared_is_found(app_dir):
    """The app closed (or crashed) mid-install: nothing ran the end of the block."""
    addonmarks.folder().mkdir(parents=True)
    (addonmarks.folder() / addonmarks.POCKET).touch()
    (addonmarks.folder() / "..bad name!").touch()          # not one of ours
    assert addonmarks.cut_off() == [addonmarks.POCKET]
    addonmarks.forget(addonmarks.POCKET)
    assert addonmarks.cut_off() == []


def _left(*keys):
    addonmarks.folder().mkdir(parents=True, exist_ok=True)
    for k in keys:
        (addonmarks.folder() / k).touch()


def _shown(window, qapp):  # noqa: F811
    window.addonctl.start()
    process_events(qapp, lambda: not window.addon_bar.isHidden())
    return window.addonctl.bar.text()


def test_nothing_cut_off_shows_nothing(window, qapp):  # noqa: F811
    window.addonctl.start()
    process_events(qapp, lambda: False, timeout=0.3)
    assert window.addon_bar.isHidden()


def test_a_cut_off_install_is_offered_again(window, qapp, monkeypatch):  # noqa: F811
    _left(addonmarks.AI_VOICES)
    asked = []
    monkeypatch.setattr(window.voice.ai, "module", None)
    monkeypatch.setattr(window.voice.ai, "_get", lambda: asked.append("get"))
    words = _shown(window, qapp)
    assert "closed while installing AI voices" in words
    assert window.addonctl.yes_btn.text() == "Install again"
    window.addonctl.yes_btn.click()
    assert asked == ["get"] and window.tabs.currentWidget() is window.voice
    assert window.addon_bar.isHidden()


def test_not_now_lets_it_be_and_asks_the_next(window, qapp, monkeypatch):  # noqa: F811
    _left(addonmarks.WATCH, addonmarks.POCKET)
    got = []
    monkeypatch.setattr(window.triggers, "get", lambda: got.append("watch"), raising=False)
    first = _shown(window, qapp)
    window.addonctl.no_btn.click()
    second = window.addonctl.bar.text()
    assert {"Onion Watch" in first, "Onion Watch" in second} == {True, False}
    assert {"Onion Pocket" in first, "Onion Pocket" in second} == {True, False}
    assert got == []
    window.addonctl.no_btn.click()
    assert window.addon_bar.isHidden()
    process_events(qapp, lambda: addonmarks.cut_off() == [])
    assert addonmarks.cut_off() == []          # not asked again next start


def test_install_again_for_onion_watch(window, qapp, monkeypatch):  # noqa: F811
    _left(addonmarks.WATCH)
    got = []
    monkeypatch.setattr(window.triggers, "get", lambda: got.append("watch"), raising=False)
    monkeypatch.setattr(window.triggers, "_busy", False, raising=False)
    _shown(window, qapp)
    window.addonctl.yes_btn.click()
    assert got == ["watch"] and window.tabs.currentWidget() is window.triggers
