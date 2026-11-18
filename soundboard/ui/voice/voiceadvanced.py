"""An alternate workspace for the voice editor, backed by its existing effect rows."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFontMetrics, QIcon
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFrame,
                               QHBoxLayout, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QScrollArea, QStyledItemDelegate,
                               QStyle, QStyleOptionViewItem, QTabBar, QVBoxLayout, QWidget)

from soundboard import voicefx
from soundboard.i18n import _, ngettext
from soundboard.ui.kit import icons, theme
from soundboard.ui.kit.panel import card, hint_label, section_label
from soundboard.ui.kit.wheelguard import no_wheel
from soundboard.ui.voice.effectrow import ADDON_GROUP, FX_ICONS, GROUPS, HERO
from soundboard.ui.voice.fxcontrols import ParamSlider


class _EffectDelegate(QStyledItemDelegate):
    """Rows grow for wrapped names and larger interface fonts."""

    def __init__(self, view: QListWidget):
        super().__init__(view)
        self.view = view

    def sizeHint(self, option, index):
        option = QStyleOptionViewItem(option)
        self.initStyleOption(option, index)
        view = self.view
        width = max(1, view.viewport().width() - 2 * view.spacing())
        text_width = max(1, width - 40)   # 8 px inset, 16 px icon, 8 px gap, 8 px inset
        bounds = QFontMetrics(option.font).boundingRect(
            QRect(0, 0, text_width, 10000), Qt.TextFlag.TextWordWrap,
            str(index.data(Qt.ItemDataRole.DisplayRole) or ""))
        return QSize(width, max(36, bounds.height() + 8))

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text, icon = opt.text, QIcon(opt.icon)
        opt.text, opt.icon = "", QIcon()
        self.view.style().drawControl(QStyle.ControlElement.CE_ItemViewItem,
                                      opt, painter, self.view)
        rtl = opt.direction == Qt.LayoutDirection.RightToLeft
        bounds = opt.rect.adjusted(8, 0, -8, 0)
        words = bounds.adjusted(0 if rtl else 24, 0, -24 if rtl else 0, 0)
        metrics = QFontMetrics(opt.font)
        flags = Qt.TextFlag.TextWordWrap | (Qt.AlignmentFlag.AlignRight if rtl
                                            else Qt.AlignmentFlag.AlignLeft)
        height = metrics.boundingRect(words, flags, text).height()
        words.setTop(opt.rect.top() + max(4, (opt.rect.height() - height) // 2))
        icon_y = round(words.top() + metrics.ascent() - metrics.capHeight() / 2 - 8)
        icon_x = bounds.right() - 15 if rtl else bounds.left()
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        painter.save()
        painter.setFont(opt.font)
        painter.setPen(QColor(theme.T["text_hi" if selected else "muted"]))
        painter.drawText(words, flags | Qt.AlignmentFlag.AlignTop, text)
        icon.paint(painter, QRect(icon_x, icon_y, 16, 16),
                   mode=QIcon.Mode.Selected if selected else QIcon.Mode.Normal)
        painter.restore()


class _EffectList(QListWidget):
    """Shared list geometry: 4 px between rows and an 8 px scrollbar gutter."""

    def __init__(self):
        super().__init__()
        self.setObjectName("settingscategories")
        self.setMinimumWidth(130)
        self.setWordWrap(True)
        self.setSpacing(2)   # each row reserves 2 px on both sides
        self.setIconSize(QSize(16, 16))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._space_scrollbar()
        self.setItemDelegate(_EffectDelegate(self))

    def _space_scrollbar(self):
        rtl = self.layoutDirection() == Qt.LayoutDirection.RightToLeft
        self.setViewportMargins(8 if rtl else 0, 0, 0 if rtl else 8, 0)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.LayoutDirectionChange:
            self._space_scrollbar()


def starting_points(etype):
    """Named recipes only change the selected effect, never the rest of a voice."""
    return {
        "echo": ((_("Subtle"), {"delay": 120, "feedback": .18, "mix": .15}),
                 (_("Strong"), {"delay": 380, "feedback": .5, "mix": .45})),
        "reverb": ((_("Small room"), {"size": .2, "predelay": 5, "mix": .18}),
                   (_("Large room"), {"size": .8, "predelay": 30, "mix": .4})),
        "voice_eq": ((_("Warm"), {"freq1": 180, "gain1": 3, "gain3": -2}),
                     (_("Clear"), {"freq1": 120, "gain1": -3, "freq3": 3500, "gain3": 3})),
        "compressor": ((_("Gentle"), {"threshold": -18, "ratio": 2, "boost": 3}),
                       (_("Strong"), {"threshold": -24, "ratio": 6, "boost": 6})),
    }.get(etype, ())


class VoiceAdvanced(QWidget):
    """Proxies edit the original rows, preserving undo, saving and Simple's controls."""

    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        self.selected = ""
        self.locked: set[str] = set()
        self.controls = {}
        self._syncing = False
        self._built_for = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        self.tabs = QTabBar()
        self.tabs.setExpanding(False)
        self.tabs.setDocumentMode(True)
        titles = (_("Add effects"), _("Your voice"), _("Effect settings"))
        for title in titles:
            self.tabs.addTab(title)
        self.tabs.currentChanged.connect(self._show_columns)
        root.addWidget(self.tabs)
        self.columns = QWidget()
        cols = QHBoxLayout(self.columns)
        cols.setContentsMargins(0, 0, 0, 0)
        cols.setSpacing(12)
        root.addWidget(self.columns, 1)
        self.cards, boxes = [], []
        for title, stretch in zip(titles, (10, 10, 17)):
            c, box = card(title)
            box.setSpacing(8)
            cols.addWidget(c, stretch)
            self.cards.append(c)
            boxes.append(box)
        self.wide = True

        self.search = QLineEdit()
        self.search.setPlaceholderText(_("Search effects"))
        self.search.setAccessibleName(_("Search effects"))
        self.search.setClearButtonEnabled(True)
        boxes[0].addWidget(self.search)
        self.category = QComboBox()
        self.category.setAccessibleName(_("Effect group"))
        no_wheel(self.category)
        self.category.addItem(_("All"), "")
        self.category.addItem(_("Pitch & voice"), _("Pitch & voice"))
        for title, _types in GROUPS:
            self.category.addItem(title, title)
        self.category.addItem(_("Finishing"), _("Finishing"))
        self.category.addItem(ADDON_GROUP, ADDON_GROUP)
        boxes[0].addWidget(self.category)
        self.browser = _EffectList()
        self.browser.setAccessibleName(_("Available effects"))
        boxes[0].addWidget(self.browser, 1)
        self.browser_hint = hint_label("")
        self.browser_hint.setWordWrap(True)
        boxes[0].addWidget(self.browser_hint)
        self.add = QPushButton(_("Add effect"))
        icons.set_icon(self.add, "plus")
        boxes[0].addWidget(self.add, 0, Qt.AlignmentFlag.AlignLeft)
        self.add.clicked.connect(self._add)
        self.browser.itemDoubleClicked.connect(lambda _item: self._add())
        self.browser.currentItemChanged.connect(self._browse)
        self.search.textChanged.connect(self._filter)
        self.category.currentIndexChanged.connect(self._filter)

        self.summary = hint_label("")
        boxes[1].addWidget(self.summary)
        self.active = _EffectList()
        self.active.setAccessibleName(_("Your voice"))
        boxes[1].addWidget(self.active, 1)
        self.empty = hint_label(_("Add an effect to start building your voice."))
        self.empty.setWordWrap(True)
        boxes[1].addWidget(self.empty)
        self.active.currentItemChanged.connect(self._pick)
        boxes[1].addWidget(hint_label(_("Effects run in the order shown.")))

        self.settings_scroll = QScrollArea()
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        boxes[2].addWidget(self.settings_scroll, 1)
        self._new_settings()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.sync)
        panel.changed.connect(self.schedule)
        self.sync()

    def _new_settings(self):
        old = self.settings_scroll.takeWidget()
        if old is not None:
            old.deleteLater()
        page = QWidget()
        self.settings = QVBoxLayout(page)
        self._space_settings_scrollbar()
        self.settings.setSpacing(12)
        self.settings_scroll.setWidget(page)
        self.controls = {}

    def _space_settings_scrollbar(self):
        rtl = self.layoutDirection() == Qt.LayoutDirection.RightToLeft
        self.settings.setContentsMargins(8 if rtl else 0, 4, 0 if rtl else 8, 8)

    @property
    def rows(self):
        return {t: r for t, r in self.panel.rows.items()
                if self.panel.EDIT_BACKGROUND or not voicefx.on_top(t)}

    def group(self, t):
        if t in HERO:
            return _("Pitch & voice")
        if t in {"voice_eq", "voice_output"}:
            return _("Finishing")
        return next((name for name, types in GROUPS if t in types), ADDON_GROUP)

    def schedule(self, *_args):
        self.timer.start(0)

    def sync(self):
        if self._syncing:
            return
        self._syncing = True
        try:
            rows = self.rows
            # Keep disabled effects here too: bypassing should never lose your place.
            present = [t for t in sorted(rows, key=lambda t: t == "voice_output")
                       if rows[t].chk.isChecked() or t == self.selected
                       or t in self.locked]
            before = [self.active.item(i).data(Qt.ItemDataRole.UserRole)
                      for i in range(self.active.count())]
            if before != present:
                self.active.blockSignals(True)
                self.active.clear()
                for t in present:
                    item = QListWidgetItem()
                    item.setData(Qt.ItemDataRole.UserRole, t)
                    self.active.addItem(item)
                self.active.blockSignals(False)
            for i in range(self.active.count()):
                item = self.active.item(i)
                t = item.data(Qt.ItemDataRole.UserRole)
                row = rows[t]
                item.setIcon(icons.icon(FX_ICONS.get(t, "sliders"), "accent_hi"))
                status = _("On") if row.chk.isChecked() else _("Off")
                suffix = _("Locked") if t in self.locked else ""
                words = (voicefx.shown(row.cls.name), status, suffix)
                item.setText(" · ".join(filter(None, words)))
                if t == self.selected:
                    self.active.setCurrentItem(item)
            if not self.selected and present:
                self.selected = present[0]
                self.active.setCurrentRow(0)
            n = sum(r.chk.isChecked() for r in rows.values())
            self.summary.setText(ngettext("{n} effect on", "{n} effects on", n))
            self.empty.setVisible(not present)
            self._filter()
            self._build_settings()
            self._sync_controls()
        finally:
            self._syncing = False

    def _filter(self, *_args):
        current = self.browser.currentItem()
        selected = current.data(Qt.ItemDataRole.UserRole) if current else None
        self.browser.blockSignals(True)
        self.browser.clear()
        query, group = self.search.text().casefold(), self.category.currentData()
        for t, row in self.rows.items():
            name = voicefx.shown(row.cls.name)
            desc = voicefx.shown(row.cls.description)
            if query not in (name + " " + desc).casefold() or (group and self.group(t) != group):
                continue
            item = QListWidgetItem(name)
            item.setIcon(icons.icon(FX_ICONS.get(t, "sliders"), "muted"))
            item.setData(Qt.ItemDataRole.UserRole, t)
            item.setToolTip(desc)
            self.browser.addItem(item)
            if t == selected:
                self.browser.setCurrentItem(item)
        if self.browser.currentRow() < 0 and self.browser.count():
            self.browser.setCurrentRow(0)
        self.browser.blockSignals(False)
        self._browse()

    def _browse(self, *_args):
        item = self.browser.currentItem()
        self.add.setEnabled(item is not None)
        if item is None:
            self.browser_hint.setText(_("No effects match your search."))
            return
        row = self.rows[item.data(Qt.ItemDataRole.UserRole)]
        self.browser_hint.setText(voicefx.shown(row.cls.description))
        self.add.setText(_("Edit effect") if row.chk.isChecked() else _("Add effect"))

    def _add(self):
        item = self.browser.currentItem()
        if item is None:
            return
        self.selected = item.data(Qt.ItemDataRole.UserRole)
        self.rows[self.selected].chk.setChecked(True)
        self.sync()
        if not self.wide:
            self.tabs.setCurrentIndex(2)

    def _pick(self, item, _previous=None):
        if self._syncing or item is None:
            return
        self.selected = item.data(Qt.ItemDataRole.UserRole)
        self._build_settings()
        self._sync_controls()
        if not self.wide:
            self.tabs.setCurrentIndex(2)

    def _build_settings(self):
        row = self.rows.get(self.selected)
        key = (self.selected, id(row))
        if key == self._built_for:
            return
        self._built_for = key
        self._new_settings()
        if row is None:
            self.settings.addWidget(hint_label(_("Select an effect to change its settings.")))
            self.settings.addStretch(1)
            return
        self.settings.addWidget(section_label(voicefx.shown(row.cls.name)))
        description = hint_label(voicefx.shown(row.cls.description))
        description.setWordWrap(True)
        self.settings.addWidget(description)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.enabled = QCheckBox(_("On"))
        self.enabled.toggled.connect(row.chk.setChecked)
        actions.addWidget(self.enabled)
        actions.addStretch(1)
        reset = QPushButton(_("Reset"))
        reset.setProperty("quiet", True)
        reset.clicked.connect(row.reset)
        actions.addWidget(reset)
        remove = QPushButton(_("Remove"))
        remove.setProperty("quiet", True)
        remove.clicked.connect(self._remove)
        actions.addWidget(remove)
        self.settings.addLayout(actions)
        self.lock = QCheckBox(_("Keep when randomizing"))
        self.lock.setToolTip(_("Randomize leaves this effect and its settings unchanged."))
        self.lock.toggled.connect(self._lock)
        self.settings.addWidget(self.lock)
        recipes = starting_points(self.selected)
        if recipes:
            self.recipe = QComboBox()
            self.recipe.setAccessibleName(_("Starting settings"))
            self.recipe.addItem(_("Starting settings"), None)
            for name, cfg in recipes:
                self.recipe.addItem(name, cfg)
            self.recipe.currentIndexChanged.connect(self._recipe)
            self.settings.addWidget(self.recipe)
        self.modified = hint_label("")
        self.settings.addWidget(self.modified)
        self.error = hint_label("")
        self.settings.addWidget(self.error)
        for q in row.cls.params:
            control = ParamSlider(q, row.state().get(q.key, q.default), compact=False)
            control.changed.connect(lambda key=q.key: self._slid(key))
            number = QDoubleSpinBox()
            scale = self._scale(q)
            number.setRange(q.lo * scale, q.hi * scale)
            number.setDecimals(1 if scale == 100 else
                               3 if q.step == 0 else 2 if q.step < .1 else 1)
            number.setSingleStep((q.step or (q.hi - q.lo) / 200) * scale)
            number.setSuffix("%" if scale == 100 else q.unit)
            number.setKeyboardTracking(False)
            number.setAccessibleName(voicefx.shown(q.label))
            number.valueChanged.connect(lambda value, key=q.key: self._number(key, value))
            if control.switch is None:
                layout = control.layout()
                assert layout is not None
                head = layout.findChildren(QHBoxLayout)[0]
                head.setSpacing(8)
                head.removeWidget(control.val)
                control.val.hide()
                head.addWidget(number)
            else:
                number.setParent(control)
                number.hide()
            self.settings.addWidget(control)
            self.controls[q.key] = (control, number)
        if self.selected == "backdrop":
            note = hint_label(_("Choose background sounds in Simple or the Effects menu."))
            note.setWordWrap(True)
            self.settings.addWidget(note)
        self.settings.addStretch(1)

    def _sync_controls(self):
        row = self.rows.get(self.selected)
        if row is None:
            return
        cfg = row.state()
        for w, val in ((self.enabled, row.chk.isChecked()),
                       (self.lock, self.selected in self.locked)):
            w.blockSignals(True)
            w.setChecked(val)
            w.blockSignals(False)
        target = self.panel.reset_target(self.selected) or {}
        changed = []
        visibility = getattr(row.cls, "shown_when", {})
        for key, (control, number) in self.controls.items():
            if rule := visibility.get(key):
                control.setVisible(cfg.get(rule[0], rule[1]) >= rule[1])
            value = cfg.get(key, control.q.default)
            for w in (control, number):
                w.blockSignals(True)
            control.set_value(value)
            number.setValue(value * self._scale(control.q))
            for w in (control, number):
                w.blockSignals(False)
            tolerance = (control.q.hi - control.q.lo) / control.steps / 2 + 1e-7
            if abs(value - target.get(key, control.q.default)) > tolerance:
                changed.append(key)
        self.modified.setText(ngettext("{n} setting changed", "{n} settings changed", len(changed))
                              if changed
                              else _("Starting settings"))
        self.error.setText(row.err.text())
        self.error.setVisible(bool(row.err.text()))

    @staticmethod
    def _scale(q):
        return 100 if 0 <= q.lo < q.hi <= 1 and not q.unit and q.step != 1 else 1

    def _number(self, key, value):
        self._write(key, value / self._scale(self.controls[key][0].q))

    def _write(self, key, value):
        row = self.rows[self.selected]
        slider = next(s for s in row.sliders if s.q.key == key)
        slider.set_value(value)
        row._slid()
        self.schedule()

    def _slid(self, key):
        self._write(key, self.controls[key][0].value())

    def _recipe(self, index):
        cfg = self.recipe.itemData(index)
        if cfg is not None:
            row = self.rows[self.selected]
            row.load({**voicefx.defaults(self.selected), **cfg, "on": True})
            self.panel._edited(self.selected)
            self.schedule()

    def _lock(self, on):
        (self.locked.add if on else self.locked.discard)(self.selected)
        self.schedule()

    def _remove(self):
        row = self.rows[self.selected]
        self.locked.discard(self.selected)
        self.selected = ""
        row.chk.setChecked(False)
        self.sync()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.wide = event.size().width() >= 1000
        self._show_columns()

    def _show_columns(self, *_args):
        self.tabs.setVisible(not self.wide)
        for i, c in enumerate(self.cards):
            c.setVisible(self.wide or i == self.tabs.currentIndex())

    def showEvent(self, event):
        super().showEvent(event)
        self.sync()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.LayoutDirectionChange and hasattr(self, "settings"):
            self._space_settings_scrollbar()
        if (event.type() in (QEvent.Type.StyleChange, QEvent.Type.PaletteChange,
                             QEvent.Type.ApplicationPaletteChange) and hasattr(self, "timer")):
            self.schedule()
