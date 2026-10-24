"""Bun the scribe: the download banner's busy picture, beside the sound's own picture.

He peeks over a small open scroll (a sheet between two wooden rollers) with a quill in
his paw, and the scroll follows the download. While a link is looked up he waits with
the quill raised and a "..." over his head; while the audio comes in he writes out the
start of a well-known tune on two rows, one note at a time, left to right, so the scroll
is as full as the download is done (a different tune each download); while it's
converted he scribbles flat out, ears flapping, sparkles rising. When it's over the
rollers wind in to meet side by side, he ties them with a ribbon and hops, then sits
with it (or, if it failed, he droops over the scroll). He never leaves: the next
download unrolls the same scroll open again (and a droop eases back to a smile), so
one pick hands over to the next without a jump. The timer only runs while a state is
animating and the widget is on screen. In lite mode (ui/settings/lite.py) there's no timer
at all: a still picture of each state, the scroll as full as the download is done.

Everything is drawn in this widget's own pixels (SLOT_W x SLOT_H), Bun himself scaled
down with soundboard/ui/bun/bunny.py's draw_bunny.
"""
from __future__ import annotations

import math
import random
import re
import time
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

from soundboard.ui.kit import theme
from soundboard.ui.bun.bunny import H, INK, W, WOOD, draw_bunny, look_colour, sparkle
from soundboard.ui.bun.bunshapes import _ellipse as _oval
from soundboard.ui.kit.pixels import snap_to_pixels
from soundboard.ui.settings import lite

SLOT_W, SLOT_H = 56, 59          # about the old thumbnail's size: Bun's head over the scroll
BUN_SCALE = 0.41                 # Bun's canvas (100 x 120) to pixels

PARCHMENT = QColor("#f3e3b8")
PARCHMENT_DARK = QColor("#d9c08a")
STAFF = QColor("#c2a56c")

# the open scroll: the rollers' centres (the top one just under his chin), how far the
# sheet runs across, a roller's radius
TOP_Y, BOT_Y = 38.0, 56.6
X0, X1 = 9.5, 46.5
ROLLER_R = 2.4
# two rows of writing, each a little five-line staff like real sheet music; the y of
# each row's bottom line. Notes stay between the D just under the staff and the G just
# over it, and stems and beams stay within a line of the staff, so the
# rows never run into each other.
ROW_BOTTOMS = (46.1, 53.0)
GAP = 0.95                       # between two lines of a staff
STEM = 2.9
HEAD_W, HEAD_H = 1.5, 1.08
NOTE_X0, ROW_END = 15.6, 43.8    # where notes start (after the clef) and where a row ends
LOW, HIGH = 29, 39               # D4 .. G5, as steps of the scale (E4, the bottom line, is 30)
MIDDLE = 34                      # B4, the middle line: notes above it get their stems down
# how much room each kind of note takes along the row, and how many beats it lasts
WIDTH = {1: 5.6, 2: 4.6, 4: 3.6, 8: 2.8, 12: 2.5, 16: 2.3}
BEATS = {1: 4.0, 2: 2.0, 4: 1.0, 8: 0.5, 12: 1 / 3, 16: 0.25}
HOP_S = 0.45                     # the finishing act: roll up, tie it and hop
OPEN_S = 0.35                    # the next download: the tied scroll unrolls (a droop lifts)
FPS = 24

# The openings of well-known pieces, all old enough to be free for anyone, written out
# a little simplified. Bars of `beats` quarter notes, then the notes: a note is its
# letter (capital for the octave from middle C, small for the one above; # sharp,
# _ flat) and its length (1 whole, 2 half, 4 quarter, 8 eighth, 16 sixteenth, 12 an
# eighth in a triplet), a dot after it for a dotted note. Notes played together are
# joined with +, R is a rest, and ( ... ) is a slur. Notes too high or low for the
# little staff are moved an octave to fit.
TUNES = {
    "Twinkle, twinkle, little star": (4, "C+E4 C4 G+e4 G4 A+f4 A4 G+e2 F+d4 F4 E+c4 E4 "
                                         "D+B8 D8 E+c8 D8 C+E2"),
    "Fur Elise": (1.5, "(e16 d#16 e16 d#16 e16 B16 d16 c16) A+E8 R16 C16 E16 A16 B+E8 R16 "
                       "E16 G#16 B16 c+A8 R16 E16 e16 d#16"),
    "Ode to joy": (4, "e+c4 e4 f+d4 g+e4 g+e4 f4 e+c4 d+B4 c+E4 c4 d+G4 e+c4 (e+c4. d8) "
                      "d+B2"),
    "Minuet in G": (3, "d+G+B4 (G8 A8 B8 c8) d+B4 G4 G4 e+c4 (c8 d8 e8 f#8) g+B4 G4 G4"),
    "The entertainer": (2, "d16 d#16 e8 c8 e8 c8 e4. c16 d16 d#16 e16 c16 d16 e8 B8 "
                           "d4 c+E4 R8"),
    "Canon in D": (4, "f#+d2 e+c#2 d+B4 (c#8 B8) A+F#4 (B8 c#8) d+B8 c#8 B8 A8 G+E4 "
                      "(F#8 E8) F#+D2"),
    "Rondo alla turca": (2, "(B16 A16 G#16 A16) c8 R8 (d16 c16 B16 c16) e8 R8 (f16 e16 "
                            "d#16 e16) B16 A16 G#16 A16 c4"),
    "Moonlight sonata": (4, "G#12 c#12 e12 G#12 c#12 e12 G#12 c#12 e12 G#12 c#12 e12 "
                            "A12 c#12 e12 A12 c#12 e12 A12 d12 f#12 A12 d12 f#12"),
    "Gymnopedie no. 1": (3, "R4 B+D2 R4 A+C#2 R4 B+D2 (f#4 a4 g4) f#4 c#4 B4 c#4 d4 A2."),
    "Prelude in C": (4, "C16 E16 G16 c16 e16 G16 c16 e16 C16 E16 G16 c16 e16 G16 c16 e16 "
                        "C16 D16 A16 d16 f16 A16 d16 f16"),
    "Eine kleine Nachtmusik": (4, "g+B4 R8 d8 g+B4 R8 d8 (g8 d8 g8 b8) d+F#2 c+A4 R8 A8 "
                                  "c+A4 R8 A8"),
    "Habanera": (2, "(d4. c#8 c8. c8 B8 B_8 A8. A_8 G8 G8 F8. E8)"),
    "The blue Danube": (3, "D4 D+F#4 A+F#4 A2 R4 a+f#4 a+f#4 R4 f#+d4 f#+d4 R4 "
                           "e+c#4 e+c#4"),
    "Dance of the sugar plum fairy": (2, "R8 B8 G8 B8 A#8 F#8 A8 G8 G4 F#8 F8 E8 E8 E8 "
                                         "e8 d#8 c#8 c8 B8"),
    "Spring": (4, "g#+e8 g#+e8 g#+e8 (f#16 e16) b+e2 b16 a16 g#+e8 g#+e8 g#+e8 "
                  "(f#16 e16) b+e2"),
    "Air on the G string": (4, "f#+A1 (f#8 B8 G8 E8 D8 C#8 D8 E8) D+F#2"),
    "Toreador song": (4, "c4. d8 c8 A4 A8 A8 G8 A8 B_8 A2. B_4 G4. c8 A4. F8 G8 D4"),
    "Swan lake": (4, "f#+A1 (B8 c#8 d8 e8) f#4. d8 f#4. d8 (f#4. B8 d8 B8 G8 d8) B2."),
    "Hungarian dance no. 5": (2, "F#4. B8 (A#8 B8 c#8 d8) B4. f#8 (e8 d8 c#8 B8) A#4 B8 "
                                 "c#8"),
    "Mary had a little lamb": (4, "E+G4 D4 C+E4 D4 E+G8 E8 E+G4 E+G2 D+F4 D4 D+F2 "
                                  "E+G4 G4 G+B2"),
    "Jingle bells": (4, "e+c4 e4 e+c2 e+c4 e4 e+c2 e+c4 g+e4 c4. d8 e+G1"),
    "Frere Jacques": (4, "C4 D4 E4 C4 C4 D4 E4 C4 E4 F4 G2 (G8 A8 G8 F8) E4 C4"),
    "Amazing grace": (3, "D4 G2 (B8 G8) B2 A4 G2 E4 D2 D4 G2 (B8 G8) B2 A8 B8 d2."),
    "William Tell overture": (2, "E16 E16 E8 E16 E16 E8 E16 E16 A8 B8 c8 E16 E16 E8 E16 "
                                 "E16 E8 E16 A16 c8 B8 G8"),
    "Maple leaf rag": (2, "R16 A_16 e_16 G_16 e_16 G16 e_16 G_16 e_16 G16 e_16 G_16 e_16 "
                          "G16 e_16 G_16"),
    "Greensleeves": (3, "A4 c2 d4 e4. f8 e4 d2 B4 G4. A8 B4 c2 A4 A4. G#8 A4 B2 G#4 E2"),
    "In the hall of the mountain king": (4, "D8 E8 F8 G8 A8 F8 A4 G#8 E8 G#4 G8 E_8 G4 "
                                            "D8 E8 F8 G8 A8 F8 A8 d8 c8 A8 F8 A8 c2"),
    "Beethoven's fifth": (2, "R8 G8 G8 G8 E_2 R8 F8 F8 F8 D2 R8 G8 G8 G8 E_8 A_8 A_8 A_8 "
                             "G8"),
    "Brahms' lullaby": (3, "E8 E8 G4. E8 E8 G4 R4 E8 G8 c4 B4. A8 A4 G4 D8 E8 F4 D4"),
}
_last_tune = [""]
_TOKEN = re.compile(r"(\(?)((?:[A-Ga-g][#_]?\+?)+|R)(16|12|1|2|4|8)(\.?)(\)?)$")
_PITCH = re.compile(r"([A-Ga-g])([#_]?)")


@dataclass
class Note:
    """One thing written on the scroll: a note, a chord (several heads on one stem) or
    a rest, and once laid out, where it sits."""
    heads: list[tuple[int, str]]     # (step of the scale, "#", "_" or "") for each head
    length: int                      # 1, 2, 4, 8, 12 (triplet eighth) or 16
    dot: bool = False
    slur_start: bool = False
    slur_end: bool = False
    row: int = 0
    x: float = 0.0
    start: float = 0.0               # beats from the start of the tune
    up: bool = True                  # its stem goes up
    stem_end: float = 0.0            # where the stem stops (a beam's height)
    beamed: bool = False

    @property
    def rest(self) -> bool:
        return not self.heads

    @property
    def beats(self) -> float:
        return BEATS[self.length] * (1.5 if self.dot else 1.0)


def parse_tune(text: str) -> list[Note]:
    notes = []
    for tok in text.split():
        m = _TOKEN.match(tok)
        if not m:
            raise ValueError(f"bad note {tok!r}")
        heads = []
        if m[2] != "R":
            for letter, acc in _PITCH.findall(m[2]):
                step = "CDEFGAB".index(letter.upper()) + 7 * (4 if letter.isupper() else 5)
                while step < LOW:
                    step += 7
                while step > HIGH:
                    step -= 7
                heads.append((step, acc))
        notes.append(Note(sorted(set(heads)), int(m[3]), m[4] == ".", m[1] == "(",
                          m[5] == ")"))
    return notes


def head_y(row: int, step: int) -> float:
    return ROW_BOTTOMS[row] - (step - 30) * GAP / 2


def lay_out(notes: list[Note], bar: float) -> tuple[list[Note], list[tuple[int, int, float]]]:
    """Put the notes along the two rows, as many as fit, with a bar line after every
    `bar` beats; join runs of short notes inside a beat with beams, and point the
    stems the way sheet music does. Returns the notes that fit and the bar lines as
    (the note they follow, row, x)."""
    placed, bars = [], []
    x, row, beat = NOTE_X0, 0, 0.0
    for n in notes:
        acc = any(a for _, a in n.heads)
        w = WIDTH[n.length] + (0.8 if n.dot else 0.0) + (1.1 if acc else 0.0)
        if x + w > ROW_END:
            row, x = row + 1, NOTE_X0
            if row == len(ROW_BOTTOMS):
                break
        n.row, n.x, n.start = row, x + (1.1 if acc else 0.0) + HEAD_W / 2, beat
        x += w
        beat += n.beats
        placed.append(n)
        if abs(beat / bar - round(beat / bar)) < 1e-6:
            bars.append((len(placed) - 1, row, x - 0.4))
            x += 0.9
    # beams: short notes (not rests) next to each other in the same beat and row
    groups, cur = [], []
    for n in placed:
        short = n.length in (8, 12, 16) and not n.rest
        if cur and (not short or n.row != cur[0].row
                    or int(n.start + 1e-6) != int(cur[0].start + 1e-6)):
            groups.append(cur)
            cur = []
        if short:
            cur.append(n)
    groups.append(cur)
    grouped = {id(n) for g in groups if len(g) > 1 for n in g}
    for g in [g for g in groups if len(g) > 1] + [[n] for n in placed if id(n) not in grouped]:
        if g[0].rest:
            continue
        steps = [s for n in g for s, _ in n.heads]
        up = sum(steps) / len(steps) < MIDDLE
        top = ROW_BOTTOMS[g[0].row] - 4 * GAP
        if up:
            end = max(min(head_y(n.row, s) for n in g for s, _ in n.heads) - STEM, top - 0.7)
        else:
            end = min(max(head_y(n.row, s) for n in g for s, _ in n.heads) + STEM,
                      ROW_BOTTOMS[g[0].row] + 0.7)
        for n in g:
            n.up, n.stem_end, n.beamed = up, end, len(g) > 1
    return placed, bars


def random_tune() -> tuple[list[Note], list[tuple[int, int, float]]]:
    """A different well-known piece each download (never the same one twice running),
    laid out on the scroll."""
    name = random.choice([n for n in TUNES if n != _last_tune[0]])
    _last_tune[0] = name
    bar, text = TUNES[name]
    return lay_out(parse_tune(text), bar)


class ScribeBunny(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFixedSize(SLOT_W, SLOT_H)
        self.state = "parsing"       # parsing | downloading | processing | done | failed
        self.prog = 0.0              # 0..1 downloaded
        self._t0 = time.monotonic()  # when the state began
        self._shown_prog = 0.0       # eased, so notes appear steadily
        self._last = time.monotonic()
        self._notes, self._bars = [], []   # reset() picks the piece
        self._from = ""              # "done" / "failed": the ending this download opens from
        # the parts that don't move from frame to frame (Bun in a pose, the scroll with
        # what's written so far) are drawn once and reused, so a frame is a few copies
        self._layers: dict[tuple, QPixmap] = {}
        self._scale = 1.0
        self._timer = QTimer(self)
        self._timer.setInterval(1000 // FPS)
        self._timer.timeout.connect(self._tick)

    def sizeHint(self) -> QSize:
        return QSize(SLOT_W, SLOT_H)

    # ------------------------------------------------------------------ state
    def reset(self):
        """A new download: back to waiting, the scroll blank, a new tune to write. After
        one that ended, the tied scroll unrolls (or the droop lifts) over OPEN_S first."""
        self._from = self.state if self.state in ("done", "failed") else ""
        self.prog = self._shown_prog = 0.0
        self._notes, self._bars = random_tune()
        self._enter("parsing")

    def set_state(self, state: str):
        if state != self.state and self.state not in ("done", "failed"):
            self._enter(state)

    def set_progress(self, frac: float):
        self.prog = max(0.0, min(1.0, float(frac)))
        self.set_state("downloading")
        if lite.on():   # (no timer: the scroll follows each step)
            self._shown_prog = self.prog
            self.update()

    def finish(self, ok: bool):
        self.prog = 1.0 if ok else self.prog
        self._enter("done" if ok else "failed")

    def settled(self) -> bool:
        """Nothing moves any more: he sits with the tied scroll, or droops over it."""
        return self.state in ("done", "failed") and self._age() >= HOP_S

    def _opening(self) -> float:
        """0..1 while the last download's ending gives way to this one (1 = just begun),
        0 once it has (or there was nothing to give way)."""
        if not self._from or self.state in ("done", "failed"):
            return 0.0
        k = self._age() / OPEN_S
        if k >= 1.0:
            self._from = ""
            return 0.0
        return 1.0 - k

    def _enter(self, state: str):
        self.state = state
        self._t0 = self._last = time.monotonic()
        self._run()

    def _age(self) -> float:
        return time.monotonic() - self._t0

    def _run(self):
        if lite.on():   # a still picture of the state: no timer, no endings playing out
            self._timer.stop()
            self._shown_prog, self._from = self.prog, ""
            self.update()
            return
        if self.isVisible() and not self.settled():
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def showEvent(self, ev):
        super().showEvent(ev)
        self._run()

    def hideEvent(self, ev):
        self._timer.stop()
        super().hideEvent(ev)

    def _tick(self):
        now = time.monotonic()
        dt, self._last = now - self._last, now
        self._shown_prog += (self.prog - self._shown_prog) * min(1.0, dt * 6)
        if self.settled():
            self._timer.stop()
        if not self.window().isMinimized():   # nothing to see: skip the frame
            self.update()

    def _layer(self, key: tuple, draw) -> QPixmap:
        """A transparent picture of the whole slot drawn by `draw(painter)`, kept by `key`."""
        key = key + (theme.T["accent"], theme.current_name, self._scale)   # name: Bun's outfit
        pm = self._layers.get(key)
        if pm is None:
            if len(self._layers) > 48:   # poses and pages of an old download
                self._layers.clear()
            dpr = self._scale
            pm = QPixmap(round(SLOT_W * dpr), round(SLOT_H * dpr))
            pm.setDevicePixelRatio(dpr)
            pm.fill(Qt.GlobalColor.transparent)
            q = QPainter(pm)
            q.setRenderHint(QPainter.RenderHint.Antialiasing)
            draw(q)
            q.end()
            self._layers[key] = pm
        return pm

    def _notes_written(self) -> float:
        """How many notes are on the scroll: in step with the download, so the scroll
        is a tenth full at 10% and all but full at 99%."""
        total = len(self._notes)
        if self.state == "processing":
            return float(total)
        return min(float(total), self._shown_prog * total)

    # --------------------------------------------------------------- painting
    def paintEvent(self, _e):
        still = lite.on()   # (lite mode: one moment, past any hop)
        t = 1.0 if still else time.monotonic()
        age = HOP_S + OPEN_S if still else self._age()
        p = QPainter(self)
        snap_to_pixels(p)
        # the kept pictures are made at the screen's real pixel size (or a zoomed render's)
        self._scale = round(max(p.device().devicePixelRatioF(), p.deviceTransform().m11()), 2)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setClipRect(self.rect())
        done = self.state == "done"
        hop = ears = 0.0
        opening = self._opening()
        sad = (1.0 if self.state == "failed" else
               round(opening, 1) if self._from == "failed" else 0.0)   # eases back
        if self.state == "processing":
            ears = 9 * math.sin(t * 16)
        if done and age < HOP_S:
            hop = -7 * math.sin(math.pi * age / HOP_S)
        blink = 1.0 if (done and age < HOP_S) or (t % 3.2) < 0.12 else 0.0
        p.translate(0, hop)
        bx = (SLOT_W - W * BUN_SCALE) / 2
        ears = round(ears)
        p.drawPixmap(0, 0, self._layer(("bun", blink, ears, sad), lambda q: draw_bunny(
            q, QRectF(bx, 0, W * BUN_SCALE, H * BUN_SCALE), None, blink=blink, ears=ears,
            sad=sad)))
        self._scroll(p, t, age)
        p.end()

    def _scroll(self, p: QPainter, t: float, age: float):
        ink = QPen(INK, 1.4)
        ink.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        ink.setCapStyle(Qt.PenCapStyle.RoundCap)
        done = self.state == "done"
        # an open scroll: a sheet between two wooden rollers, one at the top and one at
        # the bottom. When he's done the rollers wind in to meet in the middle, side by
        # side, and he ties them with a ribbon.
        roll = (min(1.0, age / HOP_S) if done else
                self._opening() if self._from == "done" else 0.0)   # unrolls for the next
        r = ROLLER_R + 1.0 * roll                  # a roller, with the paper wound on it
        mid = (TOP_Y + BOT_Y) / 2
        yt = TOP_Y + (mid - r - TOP_Y) * roll
        yb = BOT_Y + (mid + r - BOT_Y) * roll
        xl, xr = X0 + 7.0 * roll, X1 - 7.0 * roll
        def sheet(q: QPainter, partial: bool):
            if roll < 1.0:   # the sheet between the rollers, and the writing on it
                q.setPen(ink)
                q.setBrush(PARCHMENT)
                q.drawRect(QRectF(xl + 2, yt, xr - xl - 4, yb - yt))
                q.save()   # the writing rolls up with the sheet
                q.setClipRect(QRectF(xl + 2, yt, xr - xl - 4, yb - yt))
                self._staves_and_notes(q, xl, xr, partial)
                q.restore()
            self._roller(q, xl, xr, yb, r, ink)
            self._roller(q, xl, xr, yt, r, ink)

        if roll == 0.0:   # open and still: the written part is kept, the next note live
            whole = int(self._notes_written())
            p.drawPixmap(0, 0, self._layer(("sheet", id(self._notes), whole),
                                           lambda q: sheet(q, False)))
            n = self._notes_written()
            if whole < len(self._notes) and n > whole and self.state == "downloading":
                p.save()
                p.setClipRect(QRectF(xl + 2, yt + r, xr - xl - 4, yb - yt - 2 * r))
                self._note(p, self._notes[whole], n - whole)
                p.restore()
        else:
            sheet(p, True)
        if roll > 0.6:   # tied up, with a bow
            ribbon = QColor(theme.T["accent"])
            ribbon.setAlphaF(min(1.0, (roll - 0.6) / 0.4))
            edge = QPen(ink.color(), 0.9)
            p.setPen(edge)
            p.setBrush(ribbon)
            cx = (xl + xr) / 2
            p.drawRect(QRectF(cx - 1.8, yt - r - 0.5, 3.6, yb - yt + 2 * r + 1))
            for sx in (-1, 1):
                _oval(p, cx + sx * 3.4, yt - r - 1.6, 5, 3.2, ribbon, edge, sx * 25)
                p.drawLine(QPointF(cx, yt - r), QPointF(cx + sx * 4.5, yt - r - 5))
            return
        if done or self._opening():
            return
        # the quill and the paw that holds it
        if self.state == "parsing":
            nib = (X1 - 8, TOP_Y - 2 + 1.2 * math.sin(t * 3))
            for i in range(3):   # a thought: "..."
                col = QColor(theme.T["text"])
                col.setAlphaF(0.35 + 0.65 * max(0.0, math.sin(t * 5 - i * 0.9)))
                _oval(p, SLOT_W / 2 - 3 + i * 3, 6, 2.2, 2.2, col)
        elif self.state == "failed":
            nib = (X1 - 8, TOP_Y)
        else:
            n = self._notes_written()
            i = min(int(n), len(self._notes) - 1)
            if self.state == "processing":   # flat out: back and forth, down the lines
                row = int(t * 1.5) % len(ROW_BOTTOMS)
                nib = (NOTE_X0 + (0.5 + 0.5 * math.sin(t * 5)) * (ROW_END - NOTE_X0),
                       ROW_BOTTOMS[row] - 2 * GAP + 1.2 * math.sin(t * 26))
                for k in range(3):
                    ph = (t * 1.3 + k / 3) % 1.0
                    col = QColor(("#ffcf40", "#ff8fae", "#1fb6ff")[k])
                    col.setAlphaF(1.0 - ph)
                    sparkle(p, 8 + 20 * k + 3 * math.sin(t * 4 + k), 26 - 20 * ph, 2.8, col)
            elif not self._notes:   # nothing to write yet
                nib = (X1 - 8, TOP_Y)
            else:   # at the next note, dipping the nib as he writes it
                note = self._notes[i]
                y = min((head_y(note.row, s) for s, _ in note.heads),
                        default=ROW_BOTTOMS[note.row] - 2 * GAP)
                nib = (note.x + (n - int(n)) * 2.0, y + 0.6 * math.sin(t * 15))
        self._quill(p, nib[0], nib[1])

    def _roller(self, p: QPainter, xl: float, xr: float, cy: float, r: float, ink: QPen):
        """A roller: paper wound on a rod, a wooden knob at each end."""
        p.setPen(ink)
        p.setBrush(PARCHMENT_DARK)
        p.drawRoundedRect(QRectF(xl, cy - r, xr - xl, 2 * r), r, r)
        p.setPen(QPen(QColor("#f8ecc8"), 0.9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(xl + 3, cy - r * 0.35), QPointF(xr - 3, cy - r * 0.35))   # a glint
        for x in (xl - 1.6, xr + 1.6):
            _oval(p, x, cy, 4.2, 2 * r + 2.0, WOOD, QPen(INK, 1.2))
            _oval(p, x - 0.3, cy - r * 0.35, 1.3, r * 0.7, QColor("#e8b87c"))

    def _staves_and_notes(self, p: QPainter, xl: float, xr: float, partial: bool = True):
        p.setPen(QPen(STAFF, 0.3))
        for bottom in ROW_BOTTOMS:
            for k in range(5):
                p.drawLine(QPointF(xl + 3, bottom - k * GAP), QPointF(xr - 3, bottom - k * GAP))
        for row in range(len(ROW_BOTTOMS)):
            self._clef(p, xl + 4.6, row)
        n = self._notes_written()
        whole = int(n)
        notes = self._notes
        for i in range(whole):
            self._note(p, notes[i], 1.0)
        if partial and whole < len(notes) and n > whole and self.state == "downloading":
            self._note(p, notes[whole], n - whole)
        self._beams(p, notes[:whole])
        self._slurs(p, notes[:whole])
        p.setPen(QPen(STAFF.darker(130), 0.35))
        for after, row, x in self._bars:   # a bar line once its bar is written
            if after < whole:
                p.drawLine(QPointF(x, ROW_BOTTOMS[row]), QPointF(x, ROW_BOTTOMS[row] - 4 * GAP))

    def _clef(self, p: QPainter, x: float, row: int):
        """A little treble clef at the start of a row."""
        b = ROW_BOTTOMS[row]
        g = b - GAP                      # its curl wraps the G line
        path = QPainterPath(QPointF(x - 0.2, b + 1.3))
        path.quadTo(QPointF(x + 0.6, b + 0.6), QPointF(x + 0.1, b - 1.0))
        path.lineTo(QPointF(x + 0.5, b - 4 * GAP - 0.9))
        path.quadTo(QPointF(x + 1.3, b - 4 * GAP - 0.2), QPointF(x - 0.4, b - 2.2 * GAP))
        path.cubicTo(QPointF(x - 1.5, g - 1.0), QPointF(x - 0.7, g + 1.0),
                     QPointF(x + 0.4, g + 0.6))
        path.cubicTo(QPointF(x + 1.3, g + 0.1), QPointF(x + 0.6, g - 1.1),
                     QPointF(x - 0.1, g - 0.4))
        p.setPen(QPen(INK, 0.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                      Qt.PenJoinStyle.RoundJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

    def _note(self, p: QPainter, n: Note, k: float):
        """A note, chord or rest, popped in at scale `k` while it's being written."""
        mid = ROW_BOTTOMS[n.row] - 2 * GAP
        cy = mid if n.rest else sum(head_y(n.row, s) for s, _ in n.heads) / len(n.heads)
        p.save()
        p.translate(n.x, cy)
        p.scale(k, k)
        p.translate(-n.x, -cy)
        ink = QPen(INK, 0.35, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                   Qt.PenJoinStyle.RoundJoin)
        p.setPen(ink)
        p.setBrush(Qt.BrushStyle.NoBrush)
        if n.rest:
            self._rest(p, n, mid)
            p.restore()
            return
        ys = [head_y(n.row, s) for s, _ in n.heads]
        if n.length != 1:   # the stem, from the far head to the beam or its own end
            sx = n.x + (HEAD_W / 2 - 0.12 if n.up else -HEAD_W / 2 + 0.12)
            p.drawLine(QPointF(sx, max(ys) if n.up else min(ys)), QPointF(sx, n.stem_end))
            if n.length in (8, 12, 16) and not n.beamed:   # a lone short note: flags
                for f in range(2 if n.length == 16 else 1):
                    y0 = n.stem_end + (f * 0.8 if n.up else -f * 0.8)
                    flag = QPainterPath(QPointF(sx, y0))
                    d = 1 if n.up else -1
                    flag.quadTo(QPointF(sx + 1.3, y0 + 0.7 * d), QPointF(sx + 0.9, y0 + 1.9 * d))
                    p.drawPath(flag)
        for (step, acc), y in zip(n.heads, ys):
            if step <= 28 or step >= 40:   # a ledger line for notes past the staff
                p.drawLine(QPointF(n.x - 1.2, y), QPointF(n.x + 1.2, y))
            if n.length in (1, 2):         # an open head
                _oval(p, n.x, y, HEAD_W * (1.15 if n.length == 1 else 1), HEAD_H, PARCHMENT,
                      QPen(INK, 0.35), -20)
            else:
                _oval(p, n.x, y, HEAD_W, HEAD_H, INK, None, -20)
            if acc:
                self._accidental(p, n.x - HEAD_W / 2 - 0.7, y, acc)
            if n.dot:
                _oval(p, n.x + HEAD_W / 2 + 0.6, y - 0.25, 0.55, 0.55, INK)
        p.restore()

    def _rest(self, p: QPainter, n: Note, mid: float):
        x = n.x
        if n.length == 4:     # a squiggle
            path = QPainterPath(QPointF(x - 0.3, mid - 1.5))
            for dx, dy in ((0.5, -0.6), (-0.4, 0.2), (0.5, 0.9), (-0.2, 1.5)):
                path.lineTo(QPointF(x + dx, mid + dy))
            p.drawPath(path)
        elif n.length in (8, 12, 16):   # a slash with one or two blobs
            p.drawLine(QPointF(x + 0.5, mid - 0.9), QPointF(x - 0.1, mid + 1.1))
            for f in range(2 if n.length == 16 else 1):
                _oval(p, x - 0.3 - f * 0.3, mid - 0.7 + f * 0.8, 0.7, 0.7, INK)
        else:                 # a block on the middle line (half) or hanging (whole)
            y = mid - 0.5 if n.length == 2 else mid - GAP
            p.fillRect(QRectF(x - 0.8, y, 1.6, 0.5), INK)

    def _accidental(self, p: QPainter, x: float, y: float, acc: str):
        if acc == "#":
            for dx in (-0.25, 0.25):
                p.drawLine(QPointF(x + dx, y - 1.0), QPointF(x + dx, y + 1.0))
            for dy in (-0.35, 0.35):
                p.drawLine(QPointF(x - 0.55, y + dy + 0.15), QPointF(x + 0.55, y + dy - 0.15))
        else:   # a flat
            p.drawLine(QPointF(x - 0.35, y - 1.6), QPointF(x - 0.35, y + 0.5))
            bowl = QPainterPath(QPointF(x - 0.35, y - 0.1))
            bowl.quadTo(QPointF(x + 0.9, y - 0.6), QPointF(x - 0.35, y + 0.5))
            p.drawPath(bowl)

    def _beams(self, p: QPainter, written: list[Note]):
        """Join each run of beamed notes at their stems' ends: one beam for eighths, a
        second for sixteenths."""
        p.setPen(QPen(INK, 0.55, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
        for a, b in zip(written, written[1:]):
            if not (a.beamed and b.beamed and a.stem_end == b.stem_end and a.up == b.up
                    and a.row == b.row and int(a.start + 1e-6) == int(b.start + 1e-6)):
                continue
            off = HEAD_W / 2 - 0.12 if a.up else -HEAD_W / 2 + 0.12
            y = a.stem_end
            p.drawLine(QPointF(a.x + off, y), QPointF(b.x + off, y))
            if a.length == 16 and b.length == 16:
                y2 = y + (0.8 if a.up else -0.8)
                p.drawLine(QPointF(a.x + off, y2), QPointF(b.x + off, y2))

    def _slurs(self, p: QPainter, written: list[Note]):
        """A curved line over (or under) each phrase marked as a slur, once it's done."""
        p.setPen(QPen(INK, 0.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        start = None
        for n in written:
            if n.slur_start:
                start = n
            if n.slur_end and start is not None and start.row == n.row:
                run = written[written.index(start):written.index(n) + 1]
                ys = [head_y(m.row, s) for m in run for s, _ in m.heads]
                if not ys:
                    start = None
                    continue
                bottom = ROW_BOTTOMS[n.row]
                if start.up:   # stems up: the slur goes under the heads
                    y, d = min(max(ys) + 0.8, bottom + 0.6), 1.0
                else:
                    y, d = max(min(ys) - 0.8, bottom - 4 * GAP - 0.6), -1.0
                path = QPainterPath(QPointF(start.x, y))
                path.quadTo(QPointF((start.x + n.x) / 2, y + 1.2 * d), QPointF(n.x, y))
                p.drawPath(path)
                start = None

    def _quill(self, p: QPainter, x: float, y: float):
        """A feather pen held in a paw, its nib touching (x, y)."""
        p.save()
        p.translate(x, y)
        p.rotate(28)   # leaning right, out of his face
        p.scale(0.56, 0.56)
        p.setPen(QPen(INK, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(0, 0), QPointF(13, -22))
        feather = QPainterPath(QPointF(5, -9))
        feather.cubicTo(QPointF(8, -26), QPointF(24, -34), QPointF(25, -34))
        feather.cubicTo(QPointF(24, -22), QPointF(16, -10), QPointF(8, -8))
        feather.closeSubpath()
        p.setPen(QPen(INK, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                      Qt.PenJoinStyle.RoundJoin))
        p.setBrush(QColor(theme.T["accent"]).lighter(125))
        p.drawPath(feather)
        _oval(p, 4.5, -7, 12, 10, look_colour("fur"), QPen(INK, 1.8))   # the paw
        p.restore()
