"""The Pocket tab's diving Bun stands up: legs under an upright body, fins on them."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter

from soundboard.ui.bun import bunny
from soundboard.ui.pocket.divebun import DiveBun


def _drawn(stand: bool, kick: float = 0.0) -> QImage:
    """Bun on a canvas twice his height, so whatever hangs below his 100 x 120 box shows."""
    img = QImage(100, 240, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    bunny.draw_bunny(p, QRectF(0, 0, 100, 120), None, outfit=(), stand=stand, kick=kick)
    p.end()
    return img


def _painted_rows(img: QImage, y0: int, y1: int) -> int:
    return sum(any(img.pixelColor(x, y).alpha() for x in range(img.width()))
               for y in range(y0, y1))


def test_standing_bun_has_legs_below_his_body(qapp):
    # his legs reach down past the sitting body's bottom (y 120) to his ankles (~136)
    assert _painted_rows(_drawn(True), 124, 140) >= 12
    assert _painted_rows(_drawn(False), 124, 140) == 0


def test_flutter_kick_moves_his_feet_in_turn(qapp):
    (l_up, r_up), (l_dn, r_dn) = bunny.standing_feet(1.0), bunny.standing_feet(-1.0)
    assert l_up[1] < l_dn[1] and r_up[1] > r_dn[1]
    assert _drawn(True, 1.0) != _drawn(True, -1.0)


def test_dive_scene_draws_every_moment_of_its_loop(qapp):
    bun = DiveBun(160)
    for k in range(0, 60, 7):
        bun.t = k / 10
        assert not bun.grab().isNull()
