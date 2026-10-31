"""One web search hit's card (`ResultRow`): its thumbnail (`Thumb`, with the download's
progress and the player's equalizer over it), title, channel, counts and Play / Add."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QBoxLayout, QPushButton, QSizePolicy, QVBoxLayout,
                               QWidget)

from soundboard.core import jobprogress
from soundboard.ui.kit import theme
from soundboard.online import ytdl
from soundboard.ui.kit import busy, icons
from soundboard.ui.kit.panel import HoverCard
from soundboard.ui.kit.widgets import fmt_time, paint_now_playing
from soundboard.i18n import _, ngettext
from soundboard.ui.kit.pixels import snap_to_pixels
from soundboard.ui.sounds.ytlabels import ClampLabel, StatsLabel

THUMB_W, THUMB_H = 128, 72   # the pictures' shape (16:9); they fill the card's width


class Thumb(QWidget):
    """A result's picture: fills the card's width at 16:9 with rounded corners, a
    wave icon until the picture arrives."""

    def __init__(self):
        super().__init__()
        self._pm: QPixmap | None = None
        self._scaled: QPixmap | None = None   # _pm at this size: not scaled per paint
        self.now = ""   # "playing" / "paused" while it's the one in the player
        self.progress_stage = ""
        self.progress_frac = 0.0
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        policy = self.sizePolicy()
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, w: int) -> int:
        return round(w * THUMB_H / THUMB_W)

    def sizeHint(self) -> QSize:
        return QSize(THUMB_W, THUMB_H)

    def minimumSizeHint(self) -> QSize:
        return QSize(THUMB_W, THUMB_H)

    def set_pixmap(self, pm: QPixmap):
        self._pm, self._scaled = pm, None
        self.update()

    def has_picture(self) -> bool:
        return self._pm is not None

    def paintEvent(self, e):
        p = QPainter(self)
        snap_to_pixels(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, w, h), 8, 8)
        p.setClipPath(path)
        if self._pm is None:
            p.fillPath(path, QColor(128, 128, 128, 40))   # reads on light and dark
            # the theme's colour now (it was fixed when the card was made), centred by
            # its size on screen, not its pixel count (off-centre on a scaled screen)
            icons.icon("wave", "muted").paint(p, QRect((w - 32) // 2, (h - 32) // 2, 32, 32))
        else:
            # scaled to the screen's real pixels, so it isn't stretched (soft) at 125 %
            dpr = self.devicePixelRatioF()
            pw, ph = round(w * dpr), round(h * dpr)
            pm = self._scaled
            if pm is None or pm.devicePixelRatio() != dpr or not (
                    pm.width() >= pw and pm.height() >= ph and
                    (pm.width() == pw or pm.height() == ph)):
                pm = self._scaled = self._pm.scaled(pw, ph,
                                                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                                    Qt.TransformationMode.SmoothTransformation)
                pm.setDevicePixelRatio(dpr)
            size = pm.deviceIndependentSize()
            p.drawPixmap(QPointF((w - size.width()) / 2, (h - size.height()) / 2), pm)
        if self.now:
            self._paint_now(p, w, h)
        elif self.progress_stage:
            self._paint_progress(p, w, h)
        p.end()

    def _paint_progress(self, p: QPainter, w: int, h: int):
        """Overlay while downloading / parsing / processing / queued."""
        p.fillRect(QRectF(0, 0, w, h), QColor(0, 0, 0, 110))
        stage = self.progress_stage
        if stage == "parsing":
            word = _("Parsing…")
        elif stage == "processing":
            word = _("Processing…")
        elif stage == "queued":
            word = _("Queued")
        else:
            word = f"{self.progress_frac * 100:.0f}%"

        f = p.font()
        f.setBold(True)
        f.setPointSizeF(9)
        p.setFont(f)
        pill_w = p.fontMetrics().horizontalAdvance(word) + 20
        pill = QRectF((w - pill_w) / 2, (h - 22) / 2, pill_w, 22)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.T["accent"]))
        p.drawRoundedRect(pill, 11, 11)
        p.setPen(QColor(theme.T["on_accent"]))
        p.drawText(pill, Qt.AlignmentFlag.AlignCenter, word)

        if stage not in ("downloading", "processing"):
            return   # nothing measured yet: no line that would look stuck
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 120))
        p.drawRect(QRectF(0, h - 4, w, 4))
        fill_w = w * self.progress_frac   # one bar for the whole job (jobprogress)
        p.setBrush(QColor(theme.T["accent"]))
        p.drawRect(QRectF(0, h - 4, max(4.0, fill_w), 4))

    def set_progress(self, stage: str, frac: float):
        changed = (stage != self.progress_stage
                   or abs(frac - self.progress_frac) > 0.01)
        self.progress_stage = stage
        self.progress_frac = frac
        if changed:
            self.update()

    def _paint_now(self, p: QPainter, w: int, h: int):
        """The one in the player: the picture dims and a big equalizer (bouncing, or
        still while paused) with "Playing" / "Paused" sits on it."""
        p.fillRect(QRectF(0, 0, w, h), QColor(0, 0, 0, 120))
        paused = self.now == "paused"
        eq = min(44.0, h * 0.42)
        box = QRectF((w - eq) / 2, h / 2 - eq * 0.75, eq, eq)
        if paused:   # a pause sign: still bars read as dots
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#ffffff"))
            bw = eq * 0.24
            for x in (box.center().x() - bw * 1.4, box.center().x() + bw * 0.4):
                p.drawRoundedRect(QRectF(x, box.top() + eq * 0.1, bw, eq * 0.8), 3, 3)
        else:
            paint_now_playing(p, box, QColor("#ffffff"))
        f = p.font()
        f.setBold(True)
        f.setPointSizeF(9)
        p.setFont(f)
        word = _("Paused") if paused else _("Playing")
        pill_w = p.fontMetrics().horizontalAdvance(word) + 18
        pill = QRectF((w - pill_w) / 2, h / 2 + eq * 0.35, pill_w, 20)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.T["accent"]))
        p.drawRoundedRect(pill, 10, 10)
        p.setPen(QColor(theme.T["on_accent"]))
        p.drawText(pill, Qt.AlignmentFlag.AlignCenter, word)

    def set_now(self, now: str):
        changed, self.now = now != self.now, now
        if changed or now == "playing":
            self.update()   # bouncing bars: every tick while it plays


class ResultRow(HoverCard):
    """One hit as a card: picture, title, channel and length, Play and Add. `wide`: a
    pasted link's one card, picture beside the words (stacked when there's no room)."""
    play = Signal(object)
    add = Signal(object)
    WIDE_MIN_W = 560      # narrower than this, a wide card stacks like the others
    WIDE_THUMB_W = 340
    WIDE_STACKED_THUMB_H = 190

    def __init__(self, r: ytdl.Result, wide: bool = False):
        super().__init__()
        self.result = r
        self.wide = wide
        self._side: bool | None = None   # a wide card: picture beside the words (resizeEvent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setProperty("own_space", True)   # Space plays / pauses this one (spacekey.py)
        self.setAccessibleName(r.title)
        self.thumb = Thumb()
        self.title = ClampLabel(r.title)
        if wide:   # the style sheet sets the font: a setFont() would be undone
            self.title.setStyleSheet("font-size:12.5pt; font-weight:700;")
        self.playlist = r.source == ytdl.PLAYLIST   # Open lists its videos, no Play / Add
        # channel names come from YouTube: painted as plain text
        # a playlist's: how many videos it has, first so a long channel name can't cut
        # it off ("Playlist" when the search didn't say)
        sub = ((ngettext("{n} video", "{n} videos", r.videos) if r.videos else _("Playlist"),
                r.channel) if self.playlist else
               (r.channel, fmt_time(r.seconds) if r.seconds else ""))
        self.sub = ClampLabel(" · ".join(x for x in sub if x), lines=1, bold=False)
        self.sub.setObjectName("muted")
        self.stats = StatsLabel()
        self.stats.setObjectName("muted")
        self.btn_play = QPushButton(_("Play"))
        self.btn_play.setObjectName("cardplay")
        self.btn_play.setToolTip(_("Download its audio and play it once (it isn't kept)"))
        icons.set_icon(self.btn_play, "play", "on_accent", size=14)
        self.btn_play.clicked.connect(lambda: self.play.emit(self.result))
        self.btn_add = QPushButton(_("Add"))
        self.btn_add.setObjectName("cardadd")
        self.btn_add.setToolTip(_("Download its audio and add it to your sounds"))
        icons.set_icon(self.btn_add, "plus", "text_hi", size=14)
        self.btn_add.clicked.connect(lambda: self.add.emit(self.result))
        if self.playlist:   # (play: SearchResults opens it)
            self.btn_play.setText(_("Open"))
            self.btn_play.setToolTip(_("Show its videos, to add some or all of them"))
            icons.set_icon(self.btn_play, "list", "on_accent", size=14)
            self.btn_add.setText(_("Add all"))   # (add: SearchResults lists it, then queues)
            self.btn_add.setToolTip(_("Add all its videos to your sounds, without opening it"))
        for b in (self.btn_play, self.btn_add):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            if wide:   # as wide as their words (and the download's), not the whole card
                b.setMinimumWidth(140)
                b.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            else:
                b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.fill = -1.0        # the download's 0..1 (or -1: none), shown in its button
        self._job = jobprogress.JobProgress()   # every step of it on that one bar
        self._tip = ""          # its words: the buttons' tooltip while it downloads

        self.text_box = QVBoxLayout()
        self.text_box.setSpacing(6)
        for w in (self.title, self.sub, self.stats):
            self.text_box.addWidget(w)
        self.text_box.addStretch(1)
        # side by side; a playlist's Open and Add all stack when their words don't fit
        buttons = self.buttons = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        buttons.setSpacing(8)
        buttons.addWidget(self.btn_play)
        buttons.addWidget(self.btn_add)
        if wide:
            buttons.addStretch(1)
        self.text_box.addLayout(buttons)
        box = QBoxLayout(QBoxLayout.Direction.TopToBottom, self)
        box.setContentsMargins(10, 10, 10, 10) if wide else box.setContentsMargins(8, 8, 8, 8)
        box.setSpacing(14 if wide else 8)
        box.addWidget(self.thumb)
        box.addLayout(self.text_box, 1)
        # set_stats shows the label when metadata exists. Adopt it first so each
        # search result cannot flash a tiny standalone window on the desktop.
        self.stats.set_stats(r)
        self._style()
        self._release = {}      # "play" / "add" -> busy.hold's release while it's fetched
        self._added = False
        self.now = ""           # "playing" / "paused": it's the one in the player
        self.setProperty("playing", False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(_("Double-click to open") if self.playlist else _("Double-click to play"))

    def _style(self):
        """The card's two buttons: Play the filled accent, Add a quiet outline; the
        one downloading fills with the accent as it goes; Added goes quiet."""
        T = theme.T
        base = "border-radius:9px; padding:8px 12px; font-weight:600;"
        edge = theme.mix(T["card"], T["accent"], 0.5)
        styles = {
            "play": (f"QPushButton {{ {base} background:{theme.accent_fill()};"
                     f" {theme.accent_edge()} color:{T['on_accent']}; }}"
                     f"QPushButton:hover {{ background:{theme.accent_fill(hover=True)}; }}"
                     f"QPushButton:pressed {{ background:{T['accent']}; }}"),
            "add": (f"QPushButton {{ {base} background:transparent;"
                    f" border:1px solid {T['accent']}; color:{T['text_hi']}; }}"
                    f"QPushButton:hover {{ background:{T['btn_hover']}; }}"
                    f"QPushButton:pressed {{ background:{T['btn_press']}; }}"),
        }
        focus = f"QPushButton:focus {{ border:1px solid {T['text_hi']}; }}"
        # waiting for another card's download: greyed, like any busy button
        waiting = (f"QPushButton[busy=\"true\"] {{ background:{T['btn']}; border:1px solid"
                   f" {T['border']}; color:{T['muted']}; }}")
        styles = {k: v + waiting for k, v in styles.items()}
        added = (f"QPushButton {{ {base} background:transparent; border:1px solid "
                 f"{T['live_border']}; color:{T['live_text']}; }}")
        for kind, b in (("play", self.btn_play), ("add", self.btn_add)):
            css = added if kind == "add" and self._added_shown() else styles[kind]
            if kind in getattr(self, "_release", {}):
                if self.fill >= 0:
                    # the download fills it from the left: accent over the card colour
                    f = min(max(self.fill, 0.0), 1.0)
                    on, off = T["accent"], theme.mix(T["card"], T["accent"], 0.12)
                    grad = (f"qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {on}, "
                            f"stop:{f:.3f} {on}, stop:{min(f + 0.001, 1):.3f} {off}, stop:1 {off})")
                    css = (f"QPushButton {{ {base} background:{grad}; border:1px solid {edge};"
                           f" color:{T['text_hi']}; }}")
                else:
                    tint_bg = theme.mix(T["card"], T["accent"], 0.28)
                    css = (f"QPushButton {{ {base} background:{tint_bg}; border:1px solid {edge};"
                           f" color:{T['live_text']}; }}")
            css += focus
            if b.styleSheet() != css:
                b.setStyleSheet(css)

    def _added_shown(self) -> bool:
        return getattr(self, "_added", False)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.playlist:   # "Alle hinzufügen" beside "Öffnen" is cut off on a narrow card
            lay = self.layout()
            m = lay.contentsMargins() if lay is not None else None
            room = self.width() - (m.left() + m.right() if m is not None else 0)
            need = (self.btn_play.sizeHint().width() + self.btn_add.sizeHint().width()
                    + self.buttons.spacing())
            way = (QBoxLayout.Direction.TopToBottom if need > room
                   else QBoxLayout.Direction.LeftToRight)
            if self.buttons.direction() != way:
                self.buttons.setDirection(way)
        if self.wide:   # beside each other when there's room, stacked when not
            side = self.width() >= self.WIDE_MIN_W
            if side != self._side:
                self._side = side
                lay = self.layout()
                assert isinstance(lay, QBoxLayout)   # made in __init__
                lay.setDirection(QBoxLayout.Direction.LeftToRight if side
                                 else QBoxLayout.Direction.TopToBottom)
                if side:
                    self.thumb.setFixedWidth(self.WIDE_THUMB_W)
                    self.thumb.setMaximumHeight(16777215)
                else:   # a narrow window: the buttons stay in sight (the picture is cropped)
                    self.thumb.setMinimumWidth(0)
                    self.thumb.setMaximumWidth(16777215)
                    self.thumb.setMaximumHeight(self.WIDE_STACKED_THUMB_H)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, w: int) -> int:
        lay = self.layout()
        return lay.heightForWidth(w) if lay is not None else -1

    def mouseDoubleClickEvent(self, e):
        if not busy.is_busy(self.btn_play):
            self.play.emit(self.result)
        super().mouseDoubleClickEvent(e)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            if not busy.is_busy(self.btn_play):
                self.play.emit(self.result)
            e.accept()
            return
        super().keyPressEvent(e)

    def _btn(self, kind: str) -> QPushButton:
        return self.btn_add if kind == "add" else self.btn_play

    def set_now(self, now: str):
        """"playing" / "paused" while it's the one in the player, "" when it isn't:
        the picture shows it, the card is outlined and Play becomes Pause / Resume."""
        self.thumb.set_now(now)
        if now == self.now:
            return
        self.now = now
        self.setProperty("playing", bool(now))
        self.style().unpolish(self)
        self.style().polish(self)
        if "play" not in self._release:   # not while its button shows the download
            self.btn_play.setText({"playing": _("Pause"), "paused": _("Resume")}.get(
                now, _("Play")))
            icons.set_icon(self.btn_play, "pause" if now == "playing" else "play",
                           "on_accent", size=14)
        self.btn_play.setToolTip(_("Pause it") if now == "playing" else
                                 _("Carry on playing it") if now == "paused" else
                                 _("Download its audio and play it once (it isn't kept)"))

    def set_busy(self, kind: str):
        """Its audio is being fetched: that button shows how far, filling up as it
        downloads, and takes no clicks until set_done."""
        if kind in self._release or (kind == "add" and self._added):
            return
        btn = self._btn(kind)
        if not self._release:
            self.stage = "parsing"
            self.fill = 0.0
            self._job.reset()
            self._tip = _("Parsing video…")
            self.thumb.set_progress("parsing", 0.0)
        text = (_("Processing…") if self.stage == "processing" else
                (_("Adding… {pct:.0f}%", pct=self.fill * 100) if kind == "add" else
                 _("Loading… {pct:.0f}%", pct=self.fill * 100))
                if self.fill > 0 else _("Parsing…"))
        self._release[kind] = busy.hold(btn, text)
        btn.setToolTip(self._tip)
        self._style()

    def set_queued(self, kind: str):
        """This card waits for another download to finish first."""
        if kind == "add" and self._added:
            return
        btn = self._btn(kind)
        self.stage = "queued"
        self.fill = -0.5
        self._tip = _("Queued: waiting for current download to finish…")
        if kind in self._release:   # already held busy by the click (mark): relabel it
            btn.setText(_("Queued"))
        else:
            self._release[kind] = busy.hold(btn, _("Queued"))
        btn.setToolTip(self._tip)
        self.thumb.set_progress("queued", 0.0)
        self._style()

    def set_progress(self, frac):
        """0..1 of its audio downloaded, 'parsing', or below 0 / 'processing' while converted."""
        if not self._release:
            return
        # each step continues the last one's bar: it never fills up and starts again
        value = self._job.update(frac)
        if self._job.stage == "parsing":
            self.stage = "parsing"
            self.fill = value or -0.5
            self._tip = _("Parsing video…")
            self.thumb.set_progress("parsing", 0.0)
            for kind in self._release:
                btn = self._btn(kind)
                btn.setText(_("Parsing…"))
                btn.setToolTip(self._tip)
        elif self._job.stage == "processing":
            self.stage = "processing"
            self._tip = _("Processing audio…")
            self.fill = value
            self.thumb.set_progress("processing", value)
            for kind in self._release:
                btn = self._btn(kind)
                btn.setText(_("Processing…"))
                btn.setToolTip(self._tip)
        elif self._job.stage == "downloading":
            self.stage = "downloading"
            self.fill = value
            pct = self.fill * 100
            self._tip = _("Downloading audio · {value:.0f}%", value=pct)
            self.thumb.set_progress("downloading", self.fill)
            for kind in self._release:
                word = _("Adding…") if kind == "add" else _("Loading…")
                btn = self._btn(kind)
                btn.setText(f"{word} {pct:.0f}%")
                btn.setToolTip(self._tip)
        self._style()

    def set_done(self, kind: str, ok: bool):
        self.stage = ""
        self.thumb.set_progress("", 0.0)
        release = self._release.pop(kind, None)
        if not self._release:
            self.fill = -1.0
        if release is None:
            self._style()
            return
        if kind == "add" and ok:
            release()
            self._added = True
            self.btn_add.setIcon(QIcon())          # not "+ ✓ Added"
            self.btn_add.setText(_("✓ Added"))     # added once is enough
            self.btn_add.setToolTip(_("It's in your sounds now"))
            busy.set_busy(self.btn_add, True)
        else:
            release(None if ok else (_("Didn't add") if kind == "add" else _("Didn't play")))
            if kind == "play" and self.now:   # it started before the button let go
                now, self.now = self.now, ""
                self.set_now(now)
        if kind == "add" and not ok:
            self.btn_add.setToolTip(_("Download its audio and add it to your sounds"))
        elif kind == "play":
            now, self.now = self.now, None   # its tooltip again, for what it's doing now
            self.set_now(now or "")   # (only None inside this call)
        self._style()

    def set_queued_all(self, n: int):
        """A playlist's Add all: its `n` videos are in the download queue now."""
        self._added = True
        self.btn_add.setIcon(QIcon())
        self.btn_add.setText(ngettext("✓ {n} queued", "✓ {n} queued", n))
        self.btn_add.setToolTip(_("Its videos are on their way to your sounds"))
        busy.set_busy(self.btn_add, True)
        self._style()

    def set_thumb(self, pm: QPixmap):
        self.thumb.set_pixmap(pm)
