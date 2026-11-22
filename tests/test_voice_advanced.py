"""The voice workspace edits the same settings as Simple, and optional finishing DSP."""
import random

import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from soundboard import voicefx
from soundboard.ui.voice.voicefxpanel import VoiceFxPanel


@pytest.fixture
def fx(qapp):
    p = VoiceFxPanel({})
    yield p
    p.dlg.close()
    p.deleteLater()
    qapp.processEvents()


def add(fx, etype):
    a = fx.advanced_editor
    a.search.setText(voicefx.REGISTRY[etype].name)
    for i in range(a.browser.count()):
        if a.browser.item(i).data(Qt.ItemDataRole.UserRole) == etype:
            a.browser.setCurrentRow(i)
            a.add.click()
            return a
    raise AssertionError(etype)


def test_simple_and_advanced_share_edits_and_undo(fx, qapp):
    fx.pick("Robot")
    a = add(fx, "echo")
    a.controls["delay"][1].setValue(420)
    assert fx.rows["echo"].state()["delay"] == pytest.approx(420)
    QTest.qWait(450)
    snapshot = fx.spec()["effects"]
    fx.editor_modes.setCurrentIndex(1)
    fx.editor_modes.setCurrentIndex(0)
    assert fx.spec()["effects"] == snapshot
    fx.undo()
    qapp.processEvents()
    assert not fx.rows["echo"].chk.isChecked()
    fx.redo()
    qapp.processEvents()
    assert fx.rows["echo"].state()["delay"] == pytest.approx(420)


def test_search_remove_recipes_and_locks(fx, qapp):
    a = add(fx, "echo")
    a.recipe.setCurrentIndex(1)
    assert fx.rows["echo"].state()["mix"] == pytest.approx(.15)
    a.lock.setChecked(True)
    saved = fx.rows["echo"].state()
    fx.randomize(random.Random(4))
    assert fx.rows["echo"].state() == saved
    a._remove()
    qapp.processEvents()
    assert not fx.rows["echo"].chk.isChecked()
    a.search.setText("nothing matches this")
    assert a.browser.count() == 0 and not a.add.isEnabled()


def test_original_comparison_is_only_for_testing(fx):
    fx.pick("Robot")
    saved = fx.spec()["effects"]
    fx.btn_compare.click()
    assert fx.btn_test.isChecked()
    assert fx.chain_spec()["effects"] == {}
    assert fx.spec()["effects"] == saved
    fx.btn_test.click()
    assert not fx.btn_compare.isChecked()
    assert fx.chain_spec()["effects"] == saved


def test_every_effect_exposes_its_parameters_and_external_edits_stay_in_sync(fx):
    a = fx.advanced_editor
    for t, row in a.rows.items():
        a.selected = t
        a.sync()
        assert set(a.controls) == {q.key for q in row.cls.params}
    a.selected = "echo"
    a.sync()
    fx.rows["echo"].load({"on": True, "delay": 600})
    a.sync()
    assert a.controls["delay"][1].value() == 600


def test_harmony_only_shows_controls_for_the_configured_voices(fx):
    a = add(fx, "harmony")
    a.controls["voices"][1].setValue(2)
    a.sync()
    assert a.controls["third"][0].isHidden()
    assert a.controls["fourth"][0].isHidden()
    a.controls["voices"][1].setValue(4)
    a.sync()
    assert not a.controls["third"][0].isHidden()
    assert not a.controls["fourth"][0].isHidden()


def test_mouse_and_keyboard_editing_in_the_visible_workspace(fx, qapp):
    fx.dlg.resize(1240, 820)
    fx.dlg.show()
    QTest.mouseClick(fx.editor_modes, Qt.MouseButton.LeftButton,
                     pos=fx.editor_modes.tabRect(1).center())
    qapp.processEvents()
    a = fx.advanced_editor
    a.search.setFocus()
    QTest.keyClicks(a.search, "echo")
    QTest.mouseClick(a.add, Qt.MouseButton.LeftButton)
    qapp.processEvents()
    assert fx.rows["echo"].chk.isChecked()
    number = a.controls["delay"][1]
    number.setFocus()
    number.selectAll()
    QTest.keyClicks(number, "420")
    QTest.keyClick(number, Qt.Key.Key_Return)
    qapp.processEvents()
    assert fx.rows["echo"].state()["delay"] == 420
    assert fx.dlg.isVisible()


@pytest.mark.parametrize("width", [440, 640, 1000, 1240, 1700])
def test_workspace_has_card_padding_row_gaps_and_scrollbar_gutters(fx, qapp, width):
    from uicheck import assert_breathing_room

    a = fx.advanced_editor
    for row in a.rows.values():
        row.load({"on": True})
    a.selected = "voice_eq"
    a.sync()
    fx.editor_modes.setCurrentIndex(1)
    fx.dlg.resize(width, 820)
    fx.dlg.show()
    qapp.processEvents()
    for tab in range(3):
        a.tabs.setCurrentIndex(tab)
        qapp.processEvents()
        assert_breathing_room(a)
        for view in (a.browser, a.active):
            if not view.isVisibleTo(a):
                continue
            bar = view.verticalScrollBar()
            assert bar.isVisible()
            item = view.visualItemRect(view.item(0))
            item_right = view.viewport().mapTo(view, item.topRight()).x() + 1
            bar_left = bar.mapTo(view, QPoint()).x()
            assert bar_left - item_right >= 8
            second = view.visualItemRect(view.item(1))
            assert second.top() - item.bottom() - 1 >= 4
            assert not view.horizontalScrollBar().isVisible()


def test_effect_rows_grow_for_long_names(fx, qapp):
    fx.editor_modes.setCurrentIndex(1)
    fx.dlg.resize(1240, 820)
    fx.dlg.show()
    qapp.processEvents()
    view = fx.advanced_editor.browser
    first = view.item(0)
    first.setText("An exceptionally long custom effect name that wraps onto several lines")
    view.doItemsLayout()
    qapp.processEvents()
    assert view.visualItemRect(first).height() > 36


def test_scrollbar_gutter_follows_right_to_left_layout(fx, qapp):
    a = add(fx, "voice_eq")
    a.search.clear()
    fx.editor_modes.setCurrentIndex(1)
    fx.dlg.resize(1240, 760)
    fx.dlg.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    fx.dlg.show()
    qapp.processEvents()
    view = a.browser
    item = view.visualItemRect(view.item(0))
    bar = view.verticalScrollBar()
    assert bar.isVisible()
    assert view.viewport().mapTo(view, item.topLeft()).x() - (
        bar.mapTo(view, QPoint()).x() + bar.width()) >= 8
    scroll = a.settings_scroll
    bar = scroll.verticalScrollBar()
    assert bar.isVisible()
    control = a.controls["freq1"][0]
    assert control.mapTo(scroll, QPoint()).x() - (
        bar.mapTo(scroll, QPoint()).x() + bar.width()) >= 8


@pytest.mark.parametrize("rate", [8000, 16000, 48000])
def test_finishing_eq_is_flat_at_defaults_and_boosts_selected_band(rate):
    from soundboard.voicefx.builtin.advanced import VoiceEqualizer
    x = (.05 * np.sin(2 * np.pi * 1000 * np.arange(rate) / rate)).astype(np.float32)
    assert np.array_equal(VoiceEqualizer(rate).run(x, rate), x)
    eq = VoiceEqualizer(rate, {"freq2": 1000, "gain2": 6})
    y = np.concatenate([eq.run(x[i:i + 160], rate) for i in range(0, len(x), 160)])
    assert np.isfinite(y).all()
    assert np.sqrt(np.mean(y[-rate // 2:] ** 2)) > np.sqrt(np.mean(x ** 2)) * 1.8


@pytest.mark.parametrize("mix", [0, .5, 1])
def test_blend_and_output_apply_to_live_audio_and_render(mix):
    chain = voicefx.VoiceChain()
    chain.configure({"enabled": True, "effects": {
        "voice_output": {"on": True, "mix": mix, "level": -6}}})
    x = np.full((960, 2), .1, np.float32)
    expected = x * 10 ** (-6 / 20)
    assert np.allclose(chain.process(x, 48000), expected)
    assert np.allclose(chain.render(x[:, 0], 48000), expected[:, 0])


def test_new_controls_roundtrip_through_voice_share_codes(fx):
    from soundboard.mic import savedvoices
    a = add(fx, "voice_eq")
    a.controls["gain2"][1].setValue(4)
    effects = fx.spec()["effects"]
    clean = voicefx.clean_spec({"effects": effects})["effects"]
    assert clean["voice_eq"]["gain2"] == 4
    code = savedvoices.pack_code({"name": "Example", "effects": clean})
    _version, result = savedvoices.unpack_code(code)
    assert result["effects"]["voice_eq"]["gain2"] == 4


def test_blend_interpolates_the_effected_voice_and_aligns_delayed_dry(monkeypatch):
    class Delayed(voicefx.Effect):
        type = "test.delayed"
        name = "Delayed"

        def __init__(self, rate, values=None):
            super().__init__(rate, values)
            self.held = np.zeros(7, np.float32)

        def run(self, x, rate):
            joined = np.concatenate((self.held, x))
            self.held = joined[-7:].copy()
            return joined[:len(x)] * 2

        def latency(self):
            return 7 / self.rate

    monkeypatch.setitem(voicefx.REGISTRY, Delayed.type, Delayed)
    x = np.linspace(-.1, .1, 75, dtype=np.float32)
    for mix in (0, .5, 1):
        chain = voicefx.VoiceChain()
        chain.configure({"enabled": True, "effects": {
            Delayed.type: {"on": True},
            "voice_output": {"on": True, "mix": mix}}})
        mono = np.concatenate([chain.run_mono(x[i:i + 5], 48000)
                               for i in range(0, len(x), 5)])
        assert np.allclose(mono[7:], x[:-7] * (1 + mix))
        assert np.allclose(chain.render(x, 48000, block=5), x * (1 + mix))


def test_switching_to_advanced_keeps_the_window_on_screen(fx, qapp):
    # Advanced makes the window bigger: grown where it stood near the screen's
    # bottom-right corner, its Done button and close button went past the edges
    avail = fx.dlg.screen().availableGeometry()
    fx.dlg.resize(min(900, avail.width() // 2), min(600, avail.height() // 2))
    fx.dlg.show()
    qapp.processEvents()
    g = fx.dlg.frameGeometry()
    fx.dlg.move(avail.right() - g.width() - 10, avail.bottom() - g.height() - 10)
    qapp.processEvents()
    fx.editor_modes.setCurrentIndex(1)
    qapp.processEvents()
    assert fx.dlg.width() > g.width()   # it did grow
    assert avail.contains(fx.dlg.frameGeometry()), (fx.dlg.frameGeometry(), avail)
