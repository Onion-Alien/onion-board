"""Voice activation explains known input failures without waiting for the timer."""
# ruff: noqa: F811 - imported pytest fixture
from types import SimpleNamespace

import pytest

from test_voicepanel import panel  # noqa: F401


def test_enabling_voice_with_no_selected_mic_explains_it_immediately(panel):
    p, eng = panel
    eng.names = {"mic": None}
    p.fx._tile["Robot"].click()
    assert p._oops_for == p._no_mic_text()
    assert not p.oops.isHidden()
    p.poll()
    assert p._oops_for == p._no_mic_text()
    p.bar.master.click()
    assert not p.is_active()
    assert p._oops_for == "" and p.oops.isHidden()
    p.bar.master.click()
    assert p._oops_for == p._no_mic_text()


def test_enabling_voice_shows_an_existing_mic_open_failure(panel):
    p, eng = panel
    eng.names = {"mic": "Example microphone"}
    eng.errors = {"mic": "Input unavailable"}
    p.fx._tile["Robot"].click()
    assert "Input unavailable" in p._oops_for
    assert not p.oops.isHidden()
    p.fx.btn_power.click()
    assert p._oops_for == "" and p.oops.isHidden()


@pytest.mark.parametrize("selected", [None, "Example microphone"])
def test_activation_during_device_reopen_keeps_the_poll_grace(panel, selected):
    p, eng = panel
    eng.names = {"mic": selected}
    eng.devices = SimpleNamespace(busy=True)
    p.fx._tile["Robot"].click()
    assert p._oops_for == "" and p.oops.isHidden()
    p.poll()
    assert p._oops_for == "" and p.oops.isHidden()
    eng.mic_stream = object()
    eng.devices.busy = False
    p.poll()
    assert p._oops_for == "" and p.oops.isHidden()


def test_named_mic_without_a_result_keeps_grace_then_reports_failure(panel):
    p, eng = panel
    eng.names = {"mic": "Example microphone"}
    p.fx._tile["Robot"].click()
    assert p._oops_for == ""
    p.poll()
    assert p._oops_for == ""
    p.poll()
    assert p._oops_for == p._no_mic_text()


def test_activation_does_not_repeat_a_stale_error_during_reopen(panel):
    p, eng = panel
    eng.names = {"mic": "Example microphone"}
    eng.errors = {"mic": "Previous attempt failed"}
    eng.devices = SimpleNamespace(busy=True)
    p.fx._tile["Robot"].click()
    assert p._oops_for == "" and p.oops.isHidden()
    eng.errors.clear()
    eng.mic_stream = object()
    eng.devices.busy = False
    p.poll()
    assert p._oops_for == "" and p.oops.isHidden()
