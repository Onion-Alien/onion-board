"""Painting Bun and what's round him: his kept picture, the speaker and the gadget he
builds, the flying bits, his bubble, the dust and the scuffle. Part of `BunnyWidget`
(ui/bun/bunnywidget.py), whose paintEvent puts them together."""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from soundboard.ui.kit import theme
from soundboard.ui.bun.bunny import (
    draw_bunny, FUR, GADGET_SCREEN, H, INK, look_colour, PINK, PLANK_SPOT, ROBOT_CYAN,
    ROBOT_CYAN_HI, ROBOT_FUR, ROBOT_INK, sparkle, STEEL, WOOD, WOOD_DARK)
from soundboard.ui.bun import bunbubble, bunskits
from soundboard.ui.bun.bunbits import (
    BACK_END, CABINET, CLOUD_END, CROUCH, DASH_END, DUST, DUST_INK, FAIL_POOF,
    FAIL_RED, FAIL_SNAP, FINALE, PARTS, SCREEN_BARS, SPARKLE_COLORS, _steps, SWAY, _sway)

if TYPE_CHECKING:
    from typing import Any

    _Base = QWidget
else:
    _Base = object


class BunnyPaint(_Base):
    if TYPE_CHECKING:   # what BunnyWidget has that these use
        _act_t: Any
        _bun_rect: Any
        _cloud_spot: Any
        _fail_snap: Any
        _fail_t: Any
        _fin_t: Any
        _flash_at: Any
        _kept_img: Any
        _kept_key: Any
        _kept_pose: Any
        _kit: Any
        _paint_kit: Any
        _part_at: Any
        _parts: Any
        act_phase: Any
        asleep: Any
        building: Any
        bun_h: Any
        junk: Any
        puffs: Any
        robot: Any
        sparks: Any

    # ------------------------------------------------------------------ paint
    def _key(self, pose: dict, dpr: float) -> tuple:
        """What has to be the same for his kept picture to stand in for `pose`."""
        return (pose["shown"], pose["prop"], pose["smug"], pose["outfit"], self.asleep,
                self.robot, _steps(pose), self.bun_h, self.size(), dpr, theme.current_name,
                tuple(theme.T.items()))

    def _moved(self, a: dict, b: dict, dpr: float) -> float:
        """About how far (screen px) the bit of him that moved most moved from pose a
        to pose b (a colour change: always too far)."""
        if abs(a["alpha"] - b["alpha"]) > 0.5 / 255 or abs(a["led"] - b["led"]) > 0.5 / 255:
            return math.inf
        far = self.bun_h * 1.3   # (his ear tips, from his feet: the most a squash or lean moves)
        px = max(abs(a["dx"] - b["dx"]), abs(a["dy"] - b["dy"]),
                 far * abs(a["sx"] - b["sx"]), far * abs(a["sy"] - b["sy"]),
                 far * math.radians(abs(a["angle"] - b["angle"])))
        unit = self.bun_h / H
        for k, n in SWAY.items():
            px = max(px, unit * n * abs(_sway(a, k) - _sway(b, k)))
        return px * dpr

    def _picture(self, pose: dict, body: QRectF, dpr: float) -> QImage:
        """Him in `pose` on a see-through picture the size of the widget, at the
        screen's pixels: drawn once, then kept for the frames he hardly moves (_held)."""
        if pose is self._kept_pose and self._kept_img is not None:
            return self._kept_img
        size = QSize(math.ceil(self.width() * dpr), math.ceil(self.height() * dpr))
        img = self._kept_img
        if img is None or img.size() != size:
            img = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
            img.setDevicePixelRatio(dpr)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._draw_bun(p, pose, body)
        p.end()
        self._kept_img, self._kept_pose, self._kept_key = img, pose, self._key(pose, dpr)
        return img

    def _draw_bun(self, p: QPainter, pose: dict, body: QRectF):
        """Him (and what a skit puts in his paws) in `pose`, squashed, leaning and faded."""
        kit = self._kit
        p.save()
        foot = QPointF(body.center().x(), body.bottom())
        p.translate(foot)
        p.rotate(pose["angle"])
        p.scale(pose["sx"], pose["sy"])
        p.translate(-foot)
        p.setOpacity(pose["alpha"])
        draw_bunny(p, body, pose["prop"],
                   blink=pose["blink"], mouth=pose["mouth"], ears=pose["ears"],
                   swing=pose["swing"], sad=pose["sad"],
                   angry=max(pose["angry"], pose["intense"]),
                   nightcap=self.asleep, robot=self.robot, led=pose["led"],
                   nod=pose["nod"] + pose.get("tilt", 0.0), dip=pose["dip"],
                   smug=pose["smug"],
                   outfit=pose["outfit"], look=pose.get("look", 0.0),
                   kick=pose.get("kick", 0.0),
                   hold=None if kit is None else bunskits.held_paws(kit))
        if kit is not None:
            self._paint_kit(p, body, kit.front)
        p.restore()

    def _speaker(self, p: QPainter, spot: QRectF, parts: int, at: float, thump: float = 0.0):
        """The little speaker he builds, `parts` of it, on the canvas (each part springs
        on a little bigger, then settles; `at` is the act time now)."""
        def pop(i: int) -> float:
            k = (at - self._part_at[i]) / 0.25
            if k >= 1 or self._part_at[i] < 0:
                return 1.0
            return 0.4 + 0.6 * k + 0.25 * math.sin(k * math.pi)

        def scaled(rect: QRectF, k: float) -> QRectF:
            c = rect.center()
            return QRectF(c.x() - rect.width() * k / 2, c.y() - rect.height() * k / 2,
                          rect.width() * k, rect.height() * k)

        if thump:   # thumping to the beat, from the floor up
            k = 1 + 0.08 * thump
            w, h = spot.width() * k, spot.height() * k
            spot = QRectF(spot.center().x() - w / 2, spot.bottom() - h, w, h)
        ink = QPen(INK, 1.6)
        ink.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(ink)
        p.setBrush(WOOD)
        frame = scaled(spot, pop(0))
        p.drawRoundedRect(frame, 2.5, 2.5)
        if parts >= 2:
            p.setBrush(CABINET)
            p.drawRoundedRect(scaled(spot.adjusted(2.2, 2.2, -2.2, -2.2), pop(1)), 2, 2)
        cx = spot.center().x()
        if parts >= 3:
            rr = spot.width() * 0.3 * pop(2)
            cy = spot.top() + spot.height() * 0.64
            p.setPen(QPen(INK, 1.2))
            p.setBrush(STEEL)
            p.drawEllipse(QPointF(cx, cy), rr, rr)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.T["accent"]))
            p.drawEllipse(QPointF(cx, cy), rr * 0.55, rr * 0.55)
        if parts >= 4:
            rr = spot.width() * 0.14 * pop(3)
            cy = spot.top() + spot.height() * 0.25
            p.setPen(QPen(INK, 1.2))
            p.setBrush(STEEL)
            p.drawEllipse(QPointF(cx, cy), rr, rr)
        elif parts:   # a work in progress: nails waiting
            p.setPen(QPen(WOOD_DARK, 1.1, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(frame.left() + 2.5, frame.top() + 2.5),
                       QPointF(frame.left() + 4.5, frame.top() + 4.5))

    def _canvas(self, p: QPainter, body: QRectF):
        """Switch the painter to the 100 x 120 canvas `body` is drawn on."""
        s = body.height() / H
        p.translate(body.left(), body.top())
        p.scale(s, s)

    def _paint_build(self, p: QPainter, body: QRectF, rest: QRectF, pose: dict):
        """What he's building, behind him: the speaker on his plank as the blows land,
        toppling off when it fails, and playing on the floor beside him once done."""
        if self.robot or not self._parts:
            return
        f = self._fail_t
        if self.act_phase() == "hammer" or (self._fail_snap and 0 <= f < FAIL_POOF):
            p.save()
            self._canvas(p, body)
            spot = QRectF(PLANK_SPOT)
            if f >= FAIL_SNAP:   # the plank snapped: over it goes
                k = min(1.0, (f - FAIL_SNAP) / 0.35)
                pivot = QPointF(spot.right(), spot.bottom())
                p.translate(pivot)
                p.rotate(80 * k * k)
                p.translate(-pivot)
                p.translate(0, 5 * k)
                p.setOpacity(max(0.0, 1 - (f - FAIL_SNAP) / (FAIL_POOF - FAIL_SNAP)))
            self._speaker(p, spot, self._parts, self._act_t if self.building else 1e9)
            p.restore()
        elif self._fin_t >= 0:
            e = self._fin_t
            p.save()
            self._canvas(p, rest)
            p.setOpacity(max(0.0, min(1.0, (FINALE - e) / 0.7)))
            spot = PLANK_SPOT.translated(2, 119 - PLANK_SPOT.bottom())
            self._speaker(p, spot, PARTS, 1e9, abs(math.sin(e * 9)))
            p.restore()

    def _paint_screen(self, p: QPainter, body: QRectF, pose: dict):
        """Robo-Bun's gadget screen: a bar lights up a blow (the last one when it
        worked), flashing red when it shorts out."""
        if not self.robot or pose["prop"] != "wrench":
            return
        p.save()
        self._canvas(p, body)
        p.setPen(Qt.PenStyle.NoPen)
        scr = GADGET_SCREEN.adjusted(3, 1.4, -1.4, -1.4)
        gap = 0.8
        bw = (scr.width() - gap * (SCREEN_BARS - 1)) / SCREEN_BARS
        if self._fail_t >= FAIL_SNAP:
            on = int(self._fail_t * 8) % 2 == 0
            col = QColor(FAIL_RED)
            col.setAlphaF(0.9 if on else 0.35)
            p.setBrush(col)
            p.drawRect(scr)
        else:
            for i in range(SCREEN_BARS):
                col = QColor(ROBOT_CYAN if i < self._parts else "#2c3446")
                if i == self._parts and self.building:   # the next one: blinking
                    col = QColor(ROBOT_CYAN)
                    col.setAlphaF(0.25 + 0.3 * (0.5 + 0.5 * math.sin(self._act_t * 10)))
                p.setBrush(col)
                p.drawRect(QRectF(scr.left() + i * (bw + gap), scr.top(), bw, scr.height()))
        if self.act_phase() == "hammer" and 0 <= self._act_t - self._flash_at < 0.12:
            sparkle(p, 104, 106, 7, ROBOT_CYAN_HI)   # the wrench hits the bolt
        p.restore()

    def _paint_flying(self, p: QPainter, r: QRectF):
        """Junk out of the cloud, the hammer's head, and sparks."""
        s = r.height() / H
        for j in self.junk:
            p.save()
            p.setOpacity(max(0.0, min(1.0, (j.life - j.age) / 0.35)))
            p.translate(j.x, j.y)
            p.rotate(j.a)
            p.scale(s, s)
            p.setPen(QPen(INK, 1.4))
            if j.kind == "head":
                p.setBrush(STEEL)
                p.drawRoundedRect(QRectF(-10, -5, 20, 10), 2.5, 2.5)
                p.setBrush(WOOD)
                p.drawRect(QRectF(-3, 5, 6, 3))   # the stub of handle still in it
            elif j.kind == "sock":
                path = QPainterPath(QPointF(-3, -9))
                path.lineTo(3, -9)
                path.lineTo(3, 2)
                path.quadTo(QPointF(10, 2), QPointF(10, 6))
                path.quadTo(QPointF(10, 9), QPointF(4, 9))
                path.lineTo(-1, 9)
                path.quadTo(QPointF(-3, 9), QPointF(-3, 6))
                path.closeSubpath()
                p.setBrush(PINK)   # (a light sock: it shows on every theme)
                p.drawPath(path)
                p.setPen(QPen(FUR, 2))
                p.drawLine(QPointF(-2, -6.5), QPointF(2, -6.5))
            elif j.kind == "carrot":
                path = QPainterPath(QPointF(-4, -6))
                path.lineTo(4, -6)
                path.lineTo(0, 10)
                path.closeSubpath()
                p.setBrush(QColor("#ff9a3c"))
                p.drawPath(path)
                p.setPen(QPen(QColor("#2fae5a"), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawLine(QPointF(0, -6), QPointF(-3, -11))
                p.drawLine(QPointF(0, -6), QPointF(3, -11))
            elif j.kind == "spring":
                p.setPen(QPen(STEEL, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                path = QPainterPath(QPointF(-6, -8))
                for i in range(1, 7):
                    path.lineTo(6 if i % 2 else -6, -8 + i * 2.7)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPath(path)
            elif j.kind == "duck":
                p.setBrush(QColor("#ffd23f"))
                p.drawEllipse(QRectF(-8, -2, 15, 9))
                p.drawEllipse(QRectF(-1, -9, 8, 8))
                p.setBrush(QColor("#ff8a3c"))
                p.drawEllipse(QRectF(5.5, -6.5, 5, 3))
            else:   # a bit of plank
                p.setBrush(WOOD)
                p.drawRoundedRect(QRectF(-9, -2.5, 18, 5), 1.5, 1.5)
            p.restore()
        for k in self.sparks:
            col = QColor(k.col)
            col.setAlphaF(max(0.0, 1 - k.age / k.life))
            p.setPen(QPen(col, max(1.2, 1.8 * s), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(k.x, k.y), QPointF(k.x - k.vx * 0.035, k.y - k.vy * 0.035))

    def _bubble(self, p: QPainter, text: str, body: QRectF):
        """A comic speech bubble beside his face, its tail pointing at his mouth (Hoot's
        style; the same in the games and Bun mode: ui/bun/bunbubble.py)."""
        f = QFont(self.font())
        # (growing slower than he does: a big Bun's words were bigger than his head)
        f.setPixelSize(max(9, round(14 * (self.bun_h / 110) ** 0.5)))
        f.setBold(True)
        p.setFont(f)
        fm = p.fontMetrics()
        room = self.width() - 20
        lines = bunbubble.wrap(fm, text, min(room, bunbubble.side_room(body, self.width())))
        tw = max(fm.horizontalAdvance(t) for t in lines)
        if tw > room:
            return   # no room for the whole line: say nothing rather than half of it
        bw, bh = tw + 2 * bunbubble.PAD, fm.height() * len(lines) + 2 * bunbubble.PAD - 4
        bunbubble.draw(p, bunbubble.beside(body, bw, bh, self.width()), "\n".join(lines), body)

    def _paint_puffs(self, p: QPainter):
        p.setPen(Qt.PenStyle.NoPen)
        for f in self.puffs:
            k = f.age / f.life
            p.setBrush(f.col)
            p.setOpacity(0.85 * (1 - k))
            rr = f.r * (0.6 + 0.8 * k)
            p.drawEllipse(QRectF(f.x - rr, f.y - rr, 2 * rr, 2 * rr))
        p.setOpacity(1.0)

    def _paint_scuffle(self, p: QPainter):
        """The cartoon dust-up while he rummages for his tools: a jiggling cloud he dives
        into, his ears popping up out of it, stars and bits of plank flying, and he
        pops back out of it with what he went for."""
        r = self._bun_rect()
        c = self._cloud_spot()
        cx, cy = c.x(), c.y()
        t = self._act_t
        u = r.height() / 110   # (sized to him)
        phase = self.act_phase()
        if phase == "dash":    # swells round him as he dives in
            k = (t / DASH_END - CROUCH) / (1 - CROUCH)
            grow = max(0.0, min(1.0, (k - 0.1) / 0.6))
            grow = grow * grow * (3 - 2 * grow)
        elif phase == "back":  # shrinks away as he comes out
            grow = max(0.0, 1 - (t - CLOUD_END) / (BACK_END - CLOUD_END) / 0.6)
        else:
            grow = 1.0
        if grow <= 0:
            return
        if phase == "cloud":   # his ears pop up out of the top now and then
            e = (t * 2.2) % 1.0
            if e < 0.45:
                up = math.sin(e / 0.45 * math.pi)
                for ex, tilt in ((-7, -12), (7, 14)):
                    p.save()
                    p.translate(cx + ex * u + 6 * u * math.sin(t * 5), cy - 18 * u)
                    p.rotate(tilt + 8 * math.sin(t * 13))
                    p.translate(0, -16 * u * up)
                    p.setPen(QPen(ROBOT_INK if self.robot else INK, 1.6))
                    p.setBrush(ROBOT_FUR if self.robot else look_colour("fur"))
                    p.drawEllipse(QRectF(-5 * u, -12 * u, 10 * u, 26 * u))
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(ROBOT_CYAN if self.robot else look_colour("inner"))
                    p.drawEllipse(QRectF(-2.4 * u, -8 * u, 4.8 * u, 18 * u))
                    p.restore()
        p.setPen(QPen(DUST_INK, 1.5))
        p.setBrush(DUST)
        for i in range(8):
            a = i * 2 * math.pi / 8 + t * 3
            rr = (16 + 4 * math.sin(t * 23 + i * 1.9)) * grow * u
            x = cx + math.cos(a) * 25 * grow * u
            y = cy + math.sin(a) * 14 * grow * u
            p.drawEllipse(QRectF(x - rr, y - rr, 2 * rr, 2 * rr))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(cx - 28 * grow * u, cy - 16 * grow * u, 56 * grow * u, 32 * grow * u))
        k = int(t * 9)   # a new spot every few frames
        for j in range(2):
            a = (k * 2.4 + j * math.pi) % (2 * math.pi)
            x, y = cx + math.cos(a) * 38 * grow * u, cy + math.sin(a) * 22 * grow * u
            if (k + j) % 2:
                sparkle(p, x, y, 6 * grow * u, QColor(SPARKLE_COLORS[(k + j) % 4]))
            else:
                p.save()
                p.translate(x, y)
                p.rotate(math.degrees(a))
                p.setPen(QPen(INK, 1.2))
                p.setBrush(WOOD)
                p.drawRoundedRect(QRectF(-9 * grow * u, -2.8 * grow * u, 18 * grow * u,
                                         5.6 * grow * u), 1.5, 1.5)
                p.restore()
