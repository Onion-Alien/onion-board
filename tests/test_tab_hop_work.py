"""A hop through the tabs stays small on the window's fit, and Settings is kept rather than built
again for what it doesn't show. These count calls, never time."""
from dataclasses import fields

from test_mainwindow import window  # noqa: F401

from soundboard.ui.kit.crashdialog import free_dialog
from soundboard.ui.settings.settings import SettingsDialog
from soundboard.ui.window import responsive

# read by a whole Settings and still left out of its print: "sounds" (the count and lists on
# its pages are built afresh), "app_setup" (it keeps that up to date itself), the rest are
# its own open-or-shut memory and a page that's built afresh (SETTINGS_LIVE_PAGES)
READ_ANYWAY = {"sounds", "app_setup", "settings_advanced", "achievements"}


def bars_on(window, qapp, size=(1180, 624)):  # noqa: F811
    """A short window with the voices' bars on: the steps go back and forth the most."""
    window.resize(*size)
    window.show()
    window.rail.set_open(True)
    for bar in (window.voice.clean_bar, window.voice.fx, window.voice.ai):
        bar.set_paused(True)
    window.tabs.setCurrentWidget(window.sounds_page)
    qapp.processEvents()
    window.fitctl._refit()
    qapp.processEvents()


def counted(monkeypatch, name) -> list:
    calls = []
    real = getattr(responsive.Fitter, name)

    def run(self, *a, **k):
        calls.append(name)
        return real(self, *a, **k)
    monkeypatch.setattr(responsive.Fitter, name, run)
    return calls


def click_tab(window, page):  # noqa: F811
    i = window.tabs.indexOf(page)
    next(b for b in window.rail.buttons if b.index == i).click()


def hop(window, qapp):  # noqa: F811
    """Setup, Settings, Sounds, as clicks do; each with the look the timer takes after it."""
    fit = window.fitctl
    for go in (lambda: click_tab(window, window.setup_page), window.gear.click,
               lambda: click_tab(window, window.sounds_page)):
        go()
        qapp.processEvents()
        if fit._settle_timer.isActive():
            fit._settle_timer.stop()
            fit._settle()
            qapp.processEvents()


def warmed(window, qapp):  # noqa: F811
    bars_on(window, qapp)
    for _ in range(3):   # (a side is tried again until it's had one look of each kind)
        hop(window, qapp)


def test_a_hop_works_nothing_out_once_it_has_been_seen(window, qapp, monkeypatch):  # noqa: F811
    """Each hop through Setup and Settings worked the fit out again: 80 measures of the whole
    window, 130 steps undone and done again."""
    warmed(window, qapp)
    steps = counted(monkeypatch, "_apply")
    hop(window, qapp)
    assert not steps


def test_a_hop_ends_where_working_it_out_does(window, qapp, monkeypatch):  # noqa: F811
    """The steps gone after each click are the same with nothing kept, from the same start, at
    sizes where what gives way depends on what came before."""
    def clicks():
        ends = []
        for go in (lambda: click_tab(window, window.setup_page), window.gear.click,
                   lambda: click_tab(window, window.sounds_page)):
            go()
            qapp.processEvents()
            fit = window.fitctl
            if fit._settle_timer.isActive():
                fit._settle_timer.stop()
                fit._settle()
                qapp.processEvents()
            ends.append(sorted(fit._fit._at))
        return ends
    real = responsive.Fitter._start_from_kept
    for size in ((1180, 624), (760, 624), (580, 950), (640, 620)):
        bars_on(window, qapp, size)
        for _ in range(3):
            clicks()
        kept = clicks()
        monkeypatch.setattr(responsive.Fitter, "_start_from_kept", lambda self, size: None)
        worked_out = clicks()
        monkeypatch.setattr(responsive.Fitter, "_start_from_kept", real)
        assert kept == worked_out, size


def test_any_layout_asking_for_other_room_works_it_out_again(window, qapp, monkeypatch):  # noqa: F811
    """Something on a tab out of sight wanting a little more doesn't change what the window
    needs now, but it can with a step undone: what was kept isn't used."""
    warmed(window, qapp)
    scroll = window.voice._scroll
    scroll.setMinimumHeight(scroll.minimumHeight() + 1)
    qapp.processEvents()
    fit = window.fitctl._fit
    before = set(fit._kept)
    assert before, "nothing kept: this test no longer tests it"
    asked = []
    real = responsive.Fitter._start_from_kept

    def start(self, size):
        asked.append(real(self, size))
        return asked[-1]
    monkeypatch.setattr(responsive.Fitter, "_start_from_kept", start)
    click_tab(window, window.setup_page)
    monkeypatch.setattr(responsive.Fitter, "_start_from_kept", real)
    assert asked[0] is not None and asked[0] not in before, "it used what was kept before"


def test_only_a_hop_uses_what_was_kept(window, qapp, monkeypatch):  # noqa: F811
    """A resize, letting go of an edge or clicking the window look afresh."""
    bars_on(window, qapp)
    hop(window, qapp)
    used = counted(monkeypatch, "restore")
    window.resize(window.width() - 60, window.height())
    qapp.processEvents()
    window.fitctl._refit()
    window.fitctl.window_activated()
    window.fitctl._settle_timer.stop()
    window.fitctl._settle()
    assert not used


def test_settings_is_kept_when_only_what_it_doesnt_show_changed(window, qapp):  # noqa: F811
    setctl = window.setctl
    window.resize(1180, 720)
    window.show()
    setctl.preload_dialogs()
    kept = setctl._settings_kept
    cfg = window.cfg
    cfg.mic_vol, cfg.sound_vol = 0.31, 0.32
    cfg.voice_fx = {**cfg.voice_fx, "picked": "x"}
    cfg.radio = {**cfg.radio, "station": "x"}
    cfg.achievements = {**cfg.achievements, "x": 1}
    window.gear.click()
    assert setctl._settings_dlg is kept
    setctl.close_settings()
    cfg.radio = {**cfg.radio, "count_plays": not cfg.radio.get("count_plays")}   # (it shows this)
    window.gear.click()
    assert setctl._settings_dlg is not kept


def test_settings_reads_nothing_its_print_leaves_out(window, qapp):  # noqa: F811
    """What's left out of the print can't show in Settings, or a kept one would show it stale."""
    cfg = window.cfg
    names, seen = {f.name for f in fields(cfg)}, set()
    base = type(cfg)

    class Spy(base):
        def __getattribute__(self, name):
            if name in names:
                seen.add(name)
            return object.__getattribute__(self, name)
    cfg.__class__ = Spy
    try:
        dlg = SettingsDialog(window, "audio", lazy=False)
        for key in dlg._page_keys:
            dlg.show_page(key)
    finally:
        cfg.__class__ = base
    free_dialog(dlg)
    assert seen, "nothing was read: the spy no longer works"
    assert not (seen & set(window.SETTINGS_PRINT_SKIP)) - READ_ANYWAY


def test_a_fit_with_nothing_picked_doesnt_walk_the_pads(window, monkeypatch):  # noqa: F811
    monkeypatch.setattr(type(window.selection), "visible_order",
                        lambda self: (_ for _ in ()).throw(AssertionError("walked")))
    window.selection.picked.clear()
    window.padctl._fit_size_picker(True)
    window.padctl._fit_size_picker(False)


def voices_on(window, qapp, monkeypatch, size=(1188, 655)):  # noqa: F811
    """Clean mic, the voice changer and an AI voice on (as test_voice_bars_fit does), on a
    window short enough that their bars go into their cards on the Voice tab."""
    from soundboard.ui.window.tabcontrol import TAB_KEYS
    window.resize(*size)
    window.show()
    window.tabs.setCurrentIndex(TAB_KEYS.index("voice"))
    v = window.voice
    v.show_tab("fx")
    monkeypatch.setattr(v.clean, "ok", True)
    monkeypatch.setattr(v.clean, "_apply", lambda: None)
    monkeypatch.setattr(v, "_show_problem", lambda why: None)
    v.fx._tile["Robot"].click()
    v.clean.set_on(True)
    b = v.ai.b_start
    b.blockSignals(True)
    b.setChecked(True)
    b.blockSignals(False)
    v.ai.show_picked_row()
    v._emit_active()
    v._update_bar()
    for _ in range(10):
        qapp.processEvents()
    return window.tabs.currentWidget()


def test_a_hop_through_settings_leaves_the_voices_bars_where_they_are(window, qapp, monkeypatch):  # noqa: F811
    """Each hop into Setup and Settings and back moved every voice's bar out of its card
    and back (24 moves a round, each one restyled): a 2 s freeze on a slower PC."""
    voice_page = voices_on(window, qapp, monkeypatch)
    v, fit = window.voice, window.fitctl
    bars = [p.picked for k, p in v._barred() if k in ("clean", "fx", "ai")]
    assert not any(p.property("pinned") for p in bars), "not in their cards: not tested"

    def round_trip():
        for go in (lambda: click_tab(window, window.radio_page),
                   lambda: click_tab(window, window.setup_page), window.gear.click,
                   lambda: click_tab(window, window.radio_page),
                   lambda: click_tab(window, voice_page)):
            go()
            qapp.processEvents()
            if fit._settle_timer.isActive():
                fit._settle_timer.stop()
                fit._settle()
                qapp.processEvents()
    for _ in range(2):
        round_trip()
    seen = []
    for p in bars:
        real = p.setProperty
        p.setProperty = lambda name, val, _r=real: (seen.append(name), _r(name, val))[1]
    round_trip()
    assert "pinned" not in seen
    assert not any(p.property("pinned") for p in bars)   # still in their cards
    assert v._scroll.minimumHeight() == 0


def test_bars_put_off_in_settings_go_where_working_it_out_puts_them(window, qapp, monkeypatch):  # noqa: F811
    """Settings opened from the Voice tab and the window made taller there: the bars come
    back pinned under the voices, as a fit from scratch puts them."""
    voices_on(window, qapp, monkeypatch)
    v = window.voice
    window.gear.click()
    qapp.processEvents()
    window.resize(1700, 1000)
    qapp.processEvents()
    window.fitctl._refit()
    window.setctl.close_settings()
    for _ in range(5):
        qapp.processEvents()
    bars = [p.picked for k, p in v._barred() if k in ("clean", "fx", "ai")]
    assert all(p.isVisible() and p.property("pinned") for p in bars)
    assert v._scroll.minimumHeight() == v.VOICES_MIN_H
