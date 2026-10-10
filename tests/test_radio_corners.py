"""The map's cutout must reveal the window, including its gradient."""
import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QWidget

from soundboard import theme
from soundboard.library import Config
from soundboard.radio import RadioDirectory
from soundboard.ui.radiopanel import RadioTab
from test_radio import FakeEngine, FakeMeter


@pytest.mark.parametrize("name", ["Dark", "Light", "Mocha"])
@pytest.mark.parametrize("size", [(800, 600), (1180, 720)])
@pytest.mark.parametrize("populated", [False, True])
def test_map_corners_reveal_the_parent_background(
        qapp, app_dir, monkeypatch, name, size, populated):
    previous = theme.current_name
    theme.apply(qapp, name)
    root = QWidget()
    root.setObjectName("root")
    root.resize(*size)
    root.show()
    before = root.grab().toImage()
    monkeypatch.setattr(RadioDirectory, "load_outlines", lambda self: None)
    tab = RadioTab(FakeEngine(), Config(),
                   lambda: None, FakeMeter, directory=RadioDirectory(app_dir / "radio"))
    tab.setParent(root)
    tab.setGeometry(root.rect())
    tab._make_flat()
    if populated:
        tab.flat.set_land([[(-180, 84), (180, 84), (180, -58), (-180, -58)]], [])
        tab.flat.set_points([{"id": "a", "la": 50.0, "lo": 10.0, "k": 1}])
    tab.show()
    qapp.processEvents()
    after = root.grab().toImage()
    dpr = after.devicePixelRatio()
    try:
        m = tab.flat
        at = m.mapTo(root, QPoint(0, 0))
        for x, y in [(0, 0), (m.width() - 1, 0),
                     (0, m.height() - 1), (m.width() - 1, m.height() - 1)]:
            x, y = int((at.x() + x) * dpr), int((at.y() + y) * dpr)
            assert after.pixelColor(x, y) == before.pixelColor(x, y)
        # Keep the interior opaque: only the rounded cutouts reveal the parent.
        x, y = int((at.x() + m.width() // 2) * dpr), int((at.y() + 1) * dpr)
        assert after.pixelColor(x, y) != before.pixelColor(x, y)
        assert after.pixelColor(x, y).alpha() == 255
        assert m._buf.pixelColor(0, 0).alpha() == 0
        assert any(0 < m._buf.pixelColor(x, y).alpha() < 255
                   for x in range(int(12 * dpr)) for y in range(int(12 * dpr)))
    finally:
        tab.shutdown()
        root.close()
        theme.apply(qapp, previous)
