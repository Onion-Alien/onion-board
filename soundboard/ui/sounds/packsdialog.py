"""The *Free sound packs* window (Sounds tab → Backup): ready-made boards anyone can
add in one click (soundboard.sounds.packs), a few of each pack's sounds to try first (to your
headphones only), and where to share one of your own."""
from __future__ import annotations

import html
import logging
import threading
from collections import deque
from collections.abc import Callable
from pathlib import Path

import numpy as np
from PySide6.QtCore import QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout,
                               QWidget)

from soundboard.core import errors, updates
from soundboard.sounds import library, packs
from soundboard.online import net
from soundboard.audio.engine import SR
from soundboard.ui.bun import bunacts
from soundboard.ui.kit import busy, fit, icons
from soundboard.ui.kit.panel import hint_label
from soundboard.ui.kit.widgets import take_out
from soundboard.ui.kit.plaintext import plain_tip
from soundboard.i18n import _, ngettext

log = logging.getLogger(__name__)

PIC = 32          # px: a sample's picture on its button
SAMPLE_COLS = 3   # sample buttons a row
WIDTH = 620       # the window: DESIGN's widest dialog
# The window is filled a piece at a time (a pack's card, one sample's tile) with this
# long a rest between pieces. Built in one go it was ~80 ms of back-to-back Qt work,
# and the audio threads wait on the UI thread through all of it: with a few sounds
# playing, blocks came 10 ms late, a skip.
STEP_GAP_MS = 4
# plays a sample to your headphones only at a gain (None stops it); False when it
# couldn't (no headphones set)
Play = Callable[[np.ndarray | None, float], bool]


def size_text(n: int) -> str:
    return _("{n} MB", n=max(1, round(n / 1e6))) if n else ""


def meta_line(p: packs.Pack) -> str:
    """"67 sounds · 28 MB · CC0 · by Onion Board"."""
    bits = [ngettext("{n} sound", "{n} sounds", p.sounds) if p.sounds else "",
            size_text(p.size), p.license,
            _("by {name}", name=p.author) if p.author else ""]
    return " · ".join(b for b in bits if b)


def rounded(png: bytes, size: int) -> QIcon | None:
    """A sample's tile picture, `size` px square with round corners."""
    src = QPixmap()
    if not png or not src.loadFromData(png):
        return None
    src = src.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                     Qt.TransformationMode.SmoothTransformation)
    out = QPixmap(size, size)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), 6, 6)
    p.setClipPath(path)
    p.drawPixmap((size - src.width()) // 2, (size - src.height()) // 2, src)
    p.end()
    return QIcon(out)


class SampleButton(QPushButton):
    """One of a pack's sounds to try: its picture and name, lit while it plays."""

    def __init__(self):
        super().__init__()
        self.sample: packs.Sample | None = None
        self._name = ""
        self.setObjectName("voicetile")
        self.setProperty("art", True)
        self.setCheckable(True)
        self.setIconSize(QSize(PIC, PIC))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(60)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.set_sample(None)

    def set_sample(self, sample: packs.Sample | None):
        """None: an empty placeholder while the samples are fetched (no jump later)."""
        self.sample = sample
        self.setEnabled(sample is not None)
        self._name = sample.name if sample else ""
        pic = rounded(sample.picture, PIC) if sample else None
        if pic is None and sample is None:   # loading: an empty tile, as tall as a full one
            blank = QPixmap(PIC, PIC)
            blank.fill(Qt.GlobalColor.transparent)
            pic = QIcon(blank)
        self.setIcon(pic or icons.icon("play", "muted"))
        self.setAccessibleName(_("Hear {name}", name=self._name) if sample else "")
        self.setToolTip(plain_tip(_("Hear {name} (only you hear it)", name=self._name))
                        if sample else "")   # (the name comes from the pack)
        self._fit_name()

    def _fit_name(self):
        if not self.isVisible():   # not laid out yet: showing it resizes it
            self.setText(self._name.replace("&", "&&"))
            return
        room = self.width() - PIC - 30   # the picture, its gap and the padding
        shown = self.fontMetrics().elidedText(self._name, Qt.TextElideMode.ElideRight,
                                              max(0, room))
        self.setText(shown.replace("&", "&&"))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit_name()


class PackCard(QFrame):
    def __init__(self, pack: packs.Pack):
        super().__init__()
        self.pack = pack
        self.setObjectName("card")
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 12, 14, 14)
        v.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(10)
        emoji = QLabel(pack.emoji)
        emoji.setStyleSheet("font-size: 22pt; background: transparent;")
        top.addWidget(emoji, 0, Qt.AlignmentFlag.AlignTop)
        names = QVBoxLayout()
        names.setSpacing(0)
        self.name = QLabel(pack.name)
        self.name.setTextFormat(Qt.TextFormat.PlainText)
        self.name.setStyleSheet("font-weight: 600; font-size: 11pt; background: transparent;")
        names.addWidget(self.name)
        self.meta = QLabel(meta_line(pack))
        self.meta.setObjectName("muted")
        self.meta.setTextFormat(Qt.TextFormat.PlainText)
        self.meta.setWordWrap(True)
        names.addWidget(self.meta)
        top.addLayout(names, 1)
        self.btn = QPushButton()
        self.btn.setObjectName("primary")
        self.btn.clicked.connect(self._add)
        top.addWidget(self.btn, 0, Qt.AlignmentFlag.AlignTop)
        v.addLayout(top)
        if pack.description:
            about = hint_label(pack.description)
            about.setTextFormat(Qt.TextFormat.PlainText)
            v.addWidget(about)
        if pack.categories:
            cats = hint_label(_("Categories: {names}", names=", ".join(pack.categories)))
            cats.setTextFormat(Qt.TextFormat.PlainText)
            v.addWidget(cats)
        # a few of its sounds to try before adding it (packs.samples): placeholders
        # until they arrive, so the card doesn't grow under the mouse
        self.samples: list[SampleButton] = []
        self.listen = QWidget()
        grid = QGridLayout(self.listen)
        grid.setContentsMargins(0, 6, 0, 0)
        grid.setSpacing(8)
        for i in range(packs.SAMPLES):
            b = SampleButton()
            b.clicked.connect(lambda on, b=b: self._hear(b, on))
            grid.addWidget(b, i // SAMPLE_COLS, i % SAMPLE_COLS)
            self.samples.append(b)
        # into the card first: shown while it has no parent, it's a window of its own
        # for a moment (made and pulled back in: ~30 ms the sound playing waits on)
        v.addWidget(self.listen)
        self.listen.setVisible(bool(pack.preview_url))
        self.show_idle()

    def show_idle(self):
        added = self.pack.downloaded()
        self.btn.setText(_("Add again") if added else _("Add to my board"))
        self.btn.setToolTip(
            _("Adds its sounds again; ones already on your board are skipped") if added else
            _("Downloads the pack ({size}) and puts its sounds on your board, each "
              "category as its own tab", size=size_text(self.pack.size) or "?"))
        icons.set_icon(self.btn, "check" if added else "download", "on_accent")

    def show_samples(self, found: list[packs.Sample] | None):
        """Its samples arrived (none: they couldn't be fetched, so the row goes)."""
        for i in range(len(self.samples) if found else 1):
            self.show_sample(found, i)

    def show_sample(self, found: list[packs.Sample] | None, i: int):
        """show_samples for its i-th button alone (the window fills them one at a time)."""
        if not found:
            self.listen.hide()
            return
        b = self.samples[i]
        b.set_sample(found[i] if i < len(found) else None)
        b.setVisible(i < len(found))

    def _hear(self, b: SampleButton, on: bool):
        dialog = self.window()
        assert isinstance(dialog, PacksDialog)
        dialog.hear(b, on)

    def _add(self, _checked: bool = False):
        dialog = self.window()
        assert isinstance(dialog, PacksDialog)   # the cards are in one
        dialog.add(self)


class PacksDialog(QDialog):
    """`add(path)` puts a downloaded pack's sounds on the board (the window's own
    import, so it asks and reports the way dropping the zip does). `play` plays a
    pack's sample to your headphones (see Play); without it the samples don't show."""
    _listed = Signal(object, str)              # packs, why the online list wasn't read
    _progress = Signal(object, int, int)       # card, done, total
    _fetched = Signal(object, object, str)     # card, path or None, error
    _sampled = Signal(object, object)          # (pack id, preview sha), its samples
    _decoded = Signal(object, object, float, int)   # button, audio or None, gain, serial

    def __init__(self, add: Callable[[Path], None], parent=None, fetch_list: bool = True,
                 play: Play | None = None):
        super().__init__(parent)
        fit.watch(self)
        self._add = add
        self._play = play
        self._busy: set[str] = set()   # pack ids downloading now
        self._samples: dict[tuple, list] = {}   # (pack id, preview sha) -> its samples
        self._sampling: set[tuple] = set()      # ...being fetched now
        self._closed = False
        self._playing: SampleButton | None = None
        self._serial = 0               # the newest sample pressed: an older one never plays
        self._ends = QTimer(self)      # un-lights a sample once it has played out
        self._ends.setSingleShot(True)
        self._ends.timeout.connect(self._stop)
        # the packs shown, in order: a card, or a pack whose card isn't made yet (_step)
        self._slots: list[PackCard | packs.Pack] = []
        self._fills: deque[tuple[PackCard, list | None, int]] = deque()   # tiles to fill
        self._stepper = QTimer(self)
        self._stepper.setSingleShot(True)
        self._stepper.setTimerType(Qt.TimerType.PreciseTimer)
        self._stepper.timeout.connect(self._step)
        self.setWindowTitle(_("Free sound packs"))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.setSpacing(12)
        head = QHBoxLayout()
        head.setSpacing(2)   # (his widget has room round him already)
        self.bun = bunacts.ActBunny(bunacts.PAT)   # Bun with a parcel, beside the title
        head.addWidget(self.bun)
        title = QLabel(_("Free sound packs"))
        title.setObjectName("helptitle")
        head.addWidget(title, 1)
        lay.addLayout(head)
        lay.addWidget(hint_label(_(
            "Ready-made boards, free to use anywhere: in games, streams and videos. Press a "
            "sound to hear it first (only you hear it). Add a pack and its sounds land on "
            "your board, each category as its own tab.") if play is not None else _(
            "Ready-made boards, free to use anywhere: in games, streams and videos. Add one "
            "and its sounds land on your board, each category as its own tab.")))
        self.note = hint_label("")
        self.note.hide()
        lay.addWidget(self.note)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body = QWidget()
        self.list = QVBoxLayout(self.body)
        self.list.setContentsMargins(0, 0, 0, 0)
        self.list.setSpacing(12)
        self.scroll_area.setWidget(self.body)
        self.scroll_area.setMinimumSize(440, 260)
        # Keep the cards off the scroll bar; with no bar they line up with the share card.
        self.scroll_area.verticalScrollBar().rangeChanged.connect(
            lambda _lo, hi: self.list.setContentsMargins(0, 0, 10 if hi > 0 else 0, 0))
        lay.addWidget(self.scroll_area, 1)
        share = QFrame()
        share.setObjectName("card")
        sv = QHBoxLayout(share)
        sv.setContentsMargins(14, 10, 14, 10)
        sv.setSpacing(10)
        sv.addWidget(hint_label(_(
            "Made a pack? Share it: every sound must be CC0 (free for anyone, no credit "
            "needed). Once it's checked, it shows up here for everyone.")), 1)
        self.btn_share = QPushButton(_("Share a pack"))
        icons.set_icon(self.btn_share, "browser")
        self.btn_share.setToolTip(_("Opens the sharing form on GitHub in your browser"))
        self.btn_share.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(packs.SHARE_URL)))
        sv.addWidget(self.btn_share, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(share)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        box.rejected.connect(self.reject)
        lay.addWidget(box)
        self._listed.connect(self._show)
        self._progress.connect(self._on_progress)
        self._fetched.connect(self._on_fetched)
        self._sampled.connect(self._on_sampled)
        self._decoded.connect(self._on_decoded)
        self._show(packs.built_in(), "")
        self.resize(WIDTH, self._tall())
        if fetch_list and net.allowed(packs.FEATURE):
            threading.Thread(target=self._read_list, daemon=True, name="pack-list").start()
        elif fetch_list:
            self._say(net.off_message(packs.FEATURE))

    def _tall(self) -> int:
        """Room for about two packs with their samples, never past the screen."""
        screen = (self.parentWidget() or self).screen()
        room = screen.availableGeometry().height() if screen is not None else 900
        return max(480, min(760, int(room * 0.85)))

    def _say(self, text: str):
        self.note.setText(text)
        self.note.setVisible(bool(text))

    def _read_list(self):
        try:
            busy.emit(self._listed, packs.catalog(), "")
        except Exception as e:  # noqa: BLE001 - offline, switched off, a bad list…
            log.info("couldn't read the pack list: %s", e)
            busy.emit(self._listed, None, errors.plain(e))

    def _show(self, found, err: str):
        if self._closed:
            return
        if err:
            busy.toast(self, html.escape(_(
                "Couldn't get the newest list of packs ({error}), so these are the ones "
                "this version knows.", error=err)), "warn")
        if found is None or self._busy:   # don't pull a card out from under a download
            return
        if found == [s.pack if isinstance(s, PackCard) else s for s in self._slots]:
            return   # the online list is the one shown (it usually is): nothing to redo
        # Keep the cards of packs that didn't change and make only the new ones: making
        # all of them again in the open window took about 250 ms of Qt work at once,
        # and the sound playing skipped (the audio threads wait on the UI thread).
        old = {c.pack.id: c for c in self.cards}
        slots: list[PackCard | packs.Pack] = []
        for p in found:
            c = old.get(p.id)
            if c is not None and c.pack == p:
                del old[p.id]
                slots.append(c)
            else:
                slots.append(p)   # its card is made by _step
        if self._playing_card() in old.values():   # its card goes: stop its sample
            self._stop()
        while self.list.count():
            take_out(self.list)
        for c in old.values():   # packs no longer on offer (or changed)
            c.deleteLater()
        self._slots = slots
        for c in self.cards:
            self.list.addWidget(c)
        self.list.addStretch(1)
        self._make_next()   # the first new card at once: the window never opens empty
        self._stepper.start(STEP_GAP_MS)

    @property
    def cards(self) -> list[PackCard]:
        """The packs' cards made so far, in order."""
        return [s for s in self._slots if isinstance(s, PackCard)]

    def _step(self):
        """One piece of filling the window: the next pack's card, else one sample's
        tile; then a rest (STEP_GAP_MS) for the audio threads before the next one."""
        if self._closed:
            return
        if not self._make_next():
            while self._fills:
                card, found, i = self._fills.popleft()
                if card in self.cards:   # not remade meanwhile (the new one gets them)
                    card.show_sample(found, i)
                    break
        if self._fills or any(not isinstance(s, PackCard) for s in self._slots):
            self._stepper.start(STEP_GAP_MS)

    def _make_next(self) -> bool:
        """Make the first pack's card still to be made, in its place; False: none left."""
        i = next((i for i, s in enumerate(self._slots) if not isinstance(s, PackCard)), -1)
        if i < 0:
            return False
        p = self._slots[i]
        assert isinstance(p, packs.Pack)
        c = PackCard(p)
        if self._play is None:
            c.listen.hide()
        self.list.insertWidget(sum(isinstance(s, PackCard) for s in self._slots[:i]), c)
        self._slots[i] = c
        if self._play is not None and p.preview_url:
            key = (p.id, p.preview_sha256)
            if key in self._samples:   # fetched for the card this replaced
                self._fill(c, self._samples[key])
            elif key not in self._sampling:
                self._fetch_samples(c)
        return True

    def _fill(self, card: PackCard, found: list | None):
        """Its samples onto `card`, a tile a step (_step)."""
        for i in range(len(card.samples) if found else 1):
            self._fills.append((card, found, i))
        if not self._stepper.isActive():
            self._stepper.start(STEP_GAP_MS)

    def _playing_card(self) -> PackCard | None:
        """The card whose sample is playing, if one is."""
        b = self._playing
        return next((c for c in self.cards if b is not None and b in c.samples), None)

    # ------------------------------------------------------------------ samples
    def _fetch_samples(self, card: PackCard):
        """A pack's samples, fetched once (then kept on disk: the online list arriving
        remakes the cards, and asking again is free)."""
        p = card.pack
        key = (p.id, p.preview_sha256)
        self._sampling.add(key)

        def run():
            try:
                found = packs.samples(p, lambda: self._closed)
            except Exception as e:  # noqa: BLE001 - offline, switched off, a bad file
                log.info("no samples for pack %s: %s", p.id, e)
                found = None
            busy.emit(self._sampled, key, found)
        threading.Thread(target=run, daemon=True, name="pack-samples").start()

    def _on_sampled(self, key, found):
        """A pack's samples arrived: on its card now, even when the online list remade
        the cards while they were on their way."""
        self._sampling.discard(key)
        if found:
            self._samples[key] = found
        if self._closed:
            return
        for c in self.cards:
            if (c.pack.id, c.pack.preview_sha256) == key:
                self._fill(c, found)

    def hear(self, b: SampleButton, on: bool):
        """A sample pressed: play it (decoded off the UI thread), or stop it."""
        if self._playing is not None and self._playing is not b:
            self._stop()
        self._serial += 1
        self._ends.stop()
        if not on or b.sample is None or self._play is None:
            self._stop()
            return
        self._playing = b
        smp, serial = b.sample, self._serial

        def run():
            try:
                data = library.decode(str(smp.audio))
                busy.emit(self._decoded, b, data, library.level_gain(data), serial)
            except Exception:  # noqa: BLE001 - a file gone or unreadable: no sound, no crash
                log.warning("couldn't decode pack sample %s", smp.audio, exc_info=True)
                busy.emit(self._decoded, b, None, 1.0, serial)
        threading.Thread(target=run, daemon=True, name="pack-sample").start()

    def _on_decoded(self, b: SampleButton, data, gain: float, serial: int):
        if self._closed or serial != self._serial or self._play is None:
            return   # closed, or another sample (or stop) pressed meanwhile
        if data is None or not self._play(data, gain):
            self._stop()
            if data is not None:
                self._say(_("Pick your headphones in Settings → Audio to hear the samples."))
            return
        self._ends.start(int(len(data) / SR * 1000) + 150)

    def _stop(self):
        """Stop the sample playing, and un-light its button."""
        b, self._playing = self._playing, None
        self._ends.stop()
        if b is None:
            return
        try:
            b.setChecked(False)
        except RuntimeError:   # its card was remade meanwhile
            pass
        if self._play is not None:
            self._play(None, 1.0)

    # ------------------------------------------------------------------ adding
    def add(self, card: PackCard):
        p = card.pack
        if p.id in self._busy:
            return
        if not net.allowed(packs.FEATURE) and not p.downloaded():
            why = net.off_message(packs.FEATURE)
            self._say(why)
            # the note above may already say it: the press itself gets an answer too
            busy.toast(self, html.escape(why), "error")
            return
        self._busy.add(p.id)
        self.bun.set_act(bunacts.RUN)   # running with it till it lands
        busy.set_busy(card.btn, True)
        card.btn.setText(_("Downloading…"))

        def run():
            try:
                path = packs.download(
                    p, lambda done, total: busy.emit(self._progress, card, done, total),
                    lambda: self._closed)
                busy.emit(self._fetched, card, path, "")
            except updates.UpdateError as e:
                busy.emit(self._fetched, card, None, str(e))
            except Exception as e:  # noqa: BLE001 - never a crash
                log.exception("pack %s download failed", p.id)
                busy.emit(self._fetched, card, None, errors.plain(e))
        threading.Thread(target=run, daemon=True, name="pack-download").start()

    def _on_progress(self, card: PackCard, done: int, total: int):
        try:
            card.btn.setText(_("Downloading {pct}%", pct=done * 100 // total) if total
                             else _("Downloading…"))
        except RuntimeError:   # the window closed meanwhile
            pass

    def _on_fetched(self, card: PackCard, path, err: str):
        self._busy.discard(card.pack.id)
        if self._closed:
            return
        if not self._busy:
            self.bun.set_act(bunacts.PAT)
        busy.set_busy(card.btn, False)
        card.show_idle()
        if path is None:
            busy.toast(self, html.escape(_("Couldn't download {name}: {error}",
                                           name=card.pack.name, error=err)), "error")
            return
        self._say("")
        self._add(Path(path))
        self.bun.play(bunacts.OPEN)
        busy.flash(card.btn, _("✓ Added"))

    def done(self, r: int):
        self._stop()
        self._stepper.stop()
        self._closed = True   # a download still going stops at its next chunk
        super().done(r)
