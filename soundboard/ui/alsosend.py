"""Setup -> Devices -> Also send to: one row per extra device, each with its own box,
what it gets, and a − button, and a + button under them for one more. A row gets
either the same as the call (Config.also_send: a copy of what others hear) or a clean
mix for streaming (Config.obs_device, the stream output: no voice chat shaping, its
own volume, your voice or not), which brings those two settings in under it; one
device at most gets the clean mix. Built into a device grid (the Setup tab's, and
Settings -> Audio's copy of it); MainWindow.set_also_send_at / set_send_kind apply a
change and rebuild them all."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QWidget)

from soundboard import engine as eng
from soundboard.ui import icons
from soundboard.ui.panel import VolumeControl, icon_label
from soundboard.wheelguard import no_wheel
from soundboard.i18n import _

LABEL = _("Also send to")
TIP = _("Streaming, or using more than one app? Each device here gets a copy of what "
        "others hear too: Voicemeeter, a device OBS captures, a second cable, speakers...")
CALL, STREAM = "call", "stream"
KINDS = ((CALL, _("Same as the call"),
          _("Exactly what others in the call hear, shaped for voice chat")),
         (STREAM, _("Clean, for streaming"),
          _("Your sounds, screen triggers, live radio and programs in full quality (no "
            "voice chat shaping), at their own volume. In OBS: Sources → + → Audio Output "
            "Capture → this device (for a virtual cable: Audio Input Capture → its Output "
            "end). One device at a time.")))


class AlsoSendRows:
    """The rows from grid row `row` on. `icons_col`: the grid has an icon column first
    (the Setup tab) or not (Settings)."""

    def __init__(self, mw, grid: QGridLayout, row: int, icons_col: bool):
        self.mw, self.grid, self.row, self.icons_col = mw, grid, row, icons_col
        self.widgets = []
        self.add = QPushButton(_("Add a device"))
        icons.set_icon(self.add, "plus")
        self.add.setToolTip(TIP)
        self.add.clicked.connect(self._add)
        self.boxes: list[QComboBox] = []   # the device boxes, row by row
        self.kinds: list[QComboBox] = []   # ...and what each one gets
        self.stream_vol: VolumeControl | None = None
        self.stream_voice: QCheckBox | None = None
        self.rebuild()

    def rows(self) -> list[tuple[str, str]]:
        """(device, CALL / STREAM) per row: the call copies (none while sending to
        nobody), then the clean one."""
        c = self.mw.cfg
        out = [] if c.route == "off" else [(n, CALL) for n in c.also_send]
        if c.obs_device:
            out.append((c.obs_device, STREAM))
        return out

    def _add(self):
        """+: one more row, on the first device nothing sends to yet; sending to
        nobody, only the clean one makes sense."""
        free = self.free()
        if not free:
            return
        if self.mw.cfg.route == "off":
            self.mw.set_obs_device(free[0])
        else:
            self.mw.set_also_send_at(len(self.mw.cfg.also_send), free[0])

    def free(self, keep: str | None = None) -> list[str]:
        """Outputs a row can pick: not the headphones, not what already gets it (the
        picked device, the cable alongside the mic) and not another row's (`keep`: this
        row's own stays)."""
        mw, c = self.mw, self.mw.cfg
        taken = [t for t in mw.sending_to() if t != keep]
        used = [n for n in (*c.also_send, c.obs_device) if n and n != keep]
        return [n for n in (d["name"] for d in eng.list_devices("output"))
                if n != c.mon_device and n not in used
                and not any(n == t or eng.same_cable(n, t) for t in taken)]

    def _set_device(self, i: int, kind: str, name: str):
        if kind == STREAM:
            self.mw.set_obs_device(name)
        else:
            self.mw.set_also_send_at(i, name)

    def _remove(self, i: int, kind: str):
        if kind == STREAM:
            self.mw.set_obs_device(None)
        else:
            self.mw.set_also_send_at(i, None)

    def _place(self, r: int, label: QWidget, icon: bool, field: QWidget,
               minus: QWidget | None = None):
        """One grid row: (icon,) label, the field, (−)."""
        first = 1 if self.icons_col else 0
        row = [label]
        if self.icons_col:
            row.insert(0, icon_label("live") if icon else QLabel())
        for col, w in enumerate(row):
            self.grid.addWidget(w, r, col)
        self.grid.addWidget(field, r, first + 1)
        row.append(field)
        if minus is not None:
            self.grid.addWidget(minus, r, first + 2)
            row.append(minus)
        self.widgets += row

    def rebuild(self):
        for w in self.widgets:
            self.grid.removeWidget(w)
            w.hide()   # (gone at once, not when the deletion comes round)
            w.deleteLater()
        self.widgets, self.boxes, self.kinds = [], [], []
        self.stream_vol = self.stream_voice = None
        c = self.mw.cfg
        off = c.route == "off"   # sending to nobody: only the clean one goes anywhere
        first = 1 if self.icons_col else 0
        r = self.row
        for i, (name, kind) in enumerate(self.rows()):
            box = QComboBox()
            box.setMinimumWidth(120)
            box.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            box.setMinimumContentsLength(16)
            no_wheel(box)
            names = self.free(keep=name)
            if name not in names:
                names.append(name)   # unplugged, or what gets it already: still shown
            for n in names:
                box.addItem(n, n)
            box.setCurrentIndex(box.findData(name))
            box.view().setMinimumWidth(box.view().sizeHintForColumn(0) + 32)
            box.setToolTip(TIP)
            box.activated.connect(lambda _i, i=i, kind=kind, box=box: self._set_device(
                i, kind, box.currentData()))
            what = QComboBox()
            no_wheel(what)
            for k, text, tip in KINDS:
                if k == CALL and off:
                    continue   # (nothing goes to the call)
                what.addItem(text, k)
                what.setItemData(what.count() - 1, tip, Qt.ToolTipRole)
            what.setCurrentIndex(max(0, what.findData(kind)))
            fm = what.fontMetrics()   # never cut off (the theme's padding and arrow: + 90)
            what.setMinimumWidth(max(fm.horizontalAdvance(t) for __, t, __t in KINDS) + 90)
            what.setToolTip(dict((k, tip) for k, __, tip in KINDS)[kind])
            what.setAccessibleName(_("What {name} gets", name=name))
            what.activated.connect(lambda _i, name=name, what=what: self.mw.set_send_kind(
                name, what.currentData() == STREAM))
            field = QWidget()
            h = QHBoxLayout(field)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(6)
            h.addWidget(box, 1)
            h.addWidget(what)
            minus = QPushButton("−")
            minus.setObjectName("iconbutton")
            minus.setToolTip(_("Stop sending to {name}", name=name))
            minus.setAccessibleName(_("Remove {name}", name=name))
            minus.clicked.connect(lambda _c=False, i=i, kind=kind: self._remove(i, kind))
            label = QLabel(LABEL if i == 0 else "")
            label.setBuddy(box)
            self._place(r, label, i == 0, field, minus)
            self.boxes.append(box)
            self.kinds.append(what)
            r += 1
            if kind == STREAM:   # its own volume, and your voice or not, right under it
                extra = QWidget()
                h = QHBoxLayout(extra)
                h.setContentsMargins(0, 0, 0, 0)
                h.setSpacing(12)
                vol = VolumeControl(c.obs_vol, tip=_("How loud the stream output is (only "
                                                     "OBS hears it)"))
                vol.changed.connect(lambda x: self.mw.set_option("obs_vol", x))
                name_ = QLabel(_("Volume"))
                name_.setBuddy(vol.slider)
                h.addWidget(name_)
                h.addWidget(vol)
                voice = QCheckBox(_("Include my voice"))
                voice.setToolTip(_("Includes the voice changer when it's on. Untick if OBS "
                                   "already records your mic separately."))
                voice.setChecked(c.obs_voice)
                voice.toggled.connect(lambda b: self.mw.set_option("obs_voice", b))
                h.addWidget(voice)
                h.addStretch(1)
                self._place(r, QLabel(), False, extra)
                self.stream_vol, self.stream_voice = vol, voice
                r += 1
        if not self.boxes:   # no rows yet: the label goes by the + button
            label = QLabel(LABEL)
            label.setBuddy(self.add)
            row = [label]
            if self.icons_col:
                row.insert(0, icon_label("live"))
            for col, w in enumerate(row):
                self.grid.addWidget(w, r, col)
            self.widgets += row
        self.grid.addWidget(self.add, r, first + 1, Qt.AlignLeft)
        self.add.setVisible(bool(self.free()) and not (off and c.obs_device))


def build(mw, grid: QGridLayout, row: int, icons_col: bool) -> AlsoSendRows:
    """Also send to rows in `grid` from `row` on, kept up to date by `mw`."""
    rows = AlsoSendRows(mw, grid, row, icons_col)
    mw.also_views.append(rows)
    rows.add.destroyed.connect(lambda *__: mw.also_views.remove(rows)
                               if rows in mw.also_views else None)
    return rows
