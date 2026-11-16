"""Voice failures keep the controls under the pointer in the same place."""
# ruff: noqa: F811 - imported pytest fixture
import pytest
from PySide6.QtCore import QPoint

from soundboard.ui.kit import theme
from test_voicepanel import panel  # noqa: F401


def _settle(qapp):
    for _ in range(12):
        qapp.processEvents()


def _targets(p):
    controls = [*p._tabs.values(), p.fx.btn_power, p.bar.master, *p.fx._tile.values()]
    return [(w.mapTo(p, QPoint()), w.size()) for w in controls if w.isVisibleTo(p)]


@pytest.mark.parametrize("size", [(560, 700), (960, 700), (960, 1100)])
@pytest.mark.parametrize("look", ["Dark", "Light"])
def test_warning_keeps_navigation_and_switches_stationary(panel, qapp, size, look):
    p, _eng = panel
    theme.apply(qapp, look)
    p.resize(*size)
    p.show()
    p.fx.pick("Robot")
    p._show_problem("")
    _settle(qapp)
    before = _targets(p)
    height = p.height()
    p._show_problem(p._no_mic_text())
    _settle(qapp)
    assert p.oops.isVisibleTo(p)
    assert p.rect().contains(p.oops.geometry())
    assert _targets(p) == before
    assert p.height() == height
    p._show_problem("")
    _settle(qapp)
    assert _targets(p) == before
    assert p.height() == height


@pytest.mark.parametrize("height", [700, 1100, 2000])
def test_warning_keeps_targets_still_across_flow_and_scrollbar_thresholds(panel, qapp, height):
    p, _eng = panel
    theme.apply(qapp, "Dark")
    p.show()
    p.fx.pick("Robot")
    for width in range(440, 1181, 20):
        p._show_problem("")
        p.resize(width, height)
        _settle(qapp)
        before = _targets(p)
        size = p.size()
        p._show_problem(p._no_mic_text())
        _settle(qapp)
        assert _targets(p) == before, width
        assert p.size() == size, width
        p._show_problem("")
        _settle(qapp)
        assert _targets(p) == before, width
