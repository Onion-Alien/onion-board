"""Setup -> Devices -> Also send to (Config.also_send): one row per extra device that
gets a copy of what others hear, each with its own box and a − button, and a + button
under them for one more. Built into a device grid (the Setup tab's, and Settings ->
Audio's copy of it); MainWindow.set_also_send applies a change and rebuilds them all."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QGridLayout, QLabel, QPushButton

from soundboard import engine as eng
from soundboard.ui import icons
from soundboard.ui.panel import icon_label
from soundboard.wheelguard import no_wheel

LABEL = "Also send to"
TIP = ("Streaming, or using more than one app? Each device here gets a copy of what "
       "others hear too: Voicemeeter, a device OBS captures, a second cable, speakers...")


class AlsoSendRows:
    """The rows from grid row `row` on. `icons_col`: the grid has an icon column first
    (the Setup tab) or not (Settings)."""

    def __init__(self, mw, grid: QGridLayout, row: int, icons_col: bool):
        self.mw, self.grid, self.row, self.icons_col = mw, grid, row, icons_col
        self.widgets = []
        self.add = QPushButton("Add a device")
        icons.set_icon(self.add, "plus")
        self.add.setToolTip(TIP)
        self.add.clicked.connect(self._add)
        self.boxes: list[QComboBox] = []
        self.rebuild()

    def _add(self):
        """+: one more row, on the first device nothing sends to yet."""
        free = self.free()
        if free:
            self.mw.set_also_send_at(len(self.mw.cfg.also_send), free[0])

    def free(self, keep: str | None = None) -> list[str]:
        """Outputs a row can pick: not the headphones, not what already gets it (the
        picked device, the cable alongside the mic, the stream output) and not another
        row's (`keep`: this row's own stays)."""
        mw, c = self.mw, self.mw.cfg
        taken = mw.sending_to()
        used = [n for n in c.also_send if n != keep]
        return [n for n in (d["name"] for d in eng.list_devices("output"))
                if n != c.mon_device and n not in used
                and not any(n == t or eng.same_cable(n, t) for t in taken)]

    def rebuild(self):
        for w in self.widgets:
            self.grid.removeWidget(w)
            w.hide()   # (gone at once, not when the deletion comes round)
            w.deleteLater()
        self.widgets, self.boxes = [], []
        c = self.mw.cfg
        off = c.route == "off"   # sending to nobody: nothing goes anywhere
        first = 1 if self.icons_col else 0
        r = self.row
        for i, name in enumerate([] if off else c.also_send):
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
            box.activated.connect(lambda _i, i=i, box=box: self.mw.set_also_send_at(
                i, box.currentData()))
            minus = QPushButton("−")
            minus.setObjectName("iconbutton")
            minus.setToolTip(f"Stop sending to {name}")
            minus.setAccessibleName(f"Remove {name}")
            minus.clicked.connect(lambda _c=False, i=i: self.mw.set_also_send_at(i, None))
            label = QLabel(LABEL if i == 0 else "")
            label.setBuddy(box)
            row = [label, box, minus]
            if self.icons_col:
                row.insert(0, icon_label("live") if i == 0 else QLabel())
            for col, w in enumerate(row[:-2]):
                self.grid.addWidget(w, r, col)
            self.grid.addWidget(box, r, first + 1)
            self.grid.addWidget(minus, r, first + 2)
            self.widgets += row
            self.boxes.append(box)
            r += 1
        if not self.boxes and not off:   # no rows yet: the label goes by the + button
            label = QLabel(LABEL)
            label.setBuddy(self.add)
            row = [label]
            if self.icons_col:
                row.insert(0, icon_label("live"))
            for col, w in enumerate(row):
                self.grid.addWidget(w, r, col)
            self.widgets += row
        self.grid.addWidget(self.add, r, first + 1, Qt.AlignLeft)
        self.add.setVisible(not off and bool(self.free()))


def build(mw, grid: QGridLayout, row: int, icons_col: bool) -> AlsoSendRows:
    """Also send to rows in `grid` from `row` on, kept up to date by `mw`."""
    rows = AlsoSendRows(mw, grid, row, icons_col)
    mw.also_views.append(rows)
    rows.add.destroyed.connect(lambda *_: mw.also_views.remove(rows)
                               if rows in mw.also_views else None)
    return rows
