"""An alternate workspace for the voice editor, backed by its existing effect rows."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFontMetrics, QIcon
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFrame,
                               QHBoxLayout, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QScrollArea, QStyledItemDelegate,
                               QStyle, QStyleOptionViewItem, QTabBar, QVBoxLayout, QWidget)

from soundboard import voicefx
from soundboard.core import usage
from soundboard.voicefx import layers as fxlayers
from soundboard.i18n import _, ngettext
from soundboard.ui.kit import icons, theme
from soundboard.ui.kit.panel import card, hint_label, section_label
from soundboard.ui.kit.wheelguard import no_wheel
from soundboard.ui.voice.effectrow import ADDON_GROUP, FX_ICONS, GROUPS, HERO
from soundboard.ui.voice.fxcontrols import ParamSlider


INDENT = Qt.ItemDataRole.UserRole + 1   # px a row is set in (a layer's effects)


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
        # 8 px inset, 16 px icon, 8 px gap, 8 px inset, and any indent
        text_width = max(1, width - 40 - int(index.data(INDENT) or 0))
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
        indent = int(index.data(INDENT) or 0)
        bounds = opt.rect.adjusted(8 + (0 if rtl else indent), 0, -8 - (indent if rtl else 0), 0)
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



def _key(item: QListWidgetItem) -> tuple:
    """A Your voice row's ("fx", type), ("layer", i) or ("lfx", i, type)."""
    parts = str(item.data(Qt.ItemDataRole.UserRole) or "").split("|")
    return tuple(int(x) if n == 1 and parts[0] != "fx" else x for n, x in enumerate(parts))


class VoiceAdvanced(QWidget):
    """Proxies edit the original rows, preserving undo, saving and Simple's controls.

    Your voice lists your own effects (in the order they run: drag them, or Move up /
    Move down), then each voice mixed in on top as a layer with its own effects. A
    layer's effects live in the panel's `_mix` (voicefx.layers), not in rows, so the
    same effect can be in your voice and in a layer."""

    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        self.selected = ""          # your own effect that's selected ("": none)
        self.layer: int | None = None   # the layer that's selected (None: your own)
        self.layer_fx = ""          # ...and its effect ("": the layer itself)
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
        # drag your effects (and the voices mixed in) into the order they run in
        self.active.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.active.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.active.model().rowsMoved.connect(self._dropped)
        boxes[1].addWidget(self.active, 1)
        self.empty = hint_label(_("Add an effect to start building your voice."))
        self.empty.setWordWrap(True)
        boxes[1].addWidget(self.empty)
        self.active.currentItemChanged.connect(self._pick)
        order = hint_label(_("Effects run from top to bottom. Drag them to change the "
                             "order. Voices you mix in play on top of yours."))
        order.setWordWrap(True)
        boxes[1].addWidget(order)

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

    # ------------------------------------------------------------------ layers
    def _layers(self) -> list[dict]:
        return self.panel.layers()

    def _layer(self) -> dict | None:
        """The selected layer (None: your own voice, or it's gone since)."""
        stack = self._layers()
        if self.layer is not None and 0 <= self.layer < len(stack):
            return stack[self.layer]
        self.layer, self.layer_fx = None, ""
        return None

    def show_layer(self, index: int, etype: str = ""):
        """Select a layer (a chip clicked, a voice just mixed in) or one of its effects."""
        self.layer, self.layer_fx = index, etype
        self.sync()
        if not self.wide:
            self.tabs.setCurrentIndex(2 if etype else 1)

    def _order(self) -> list[str]:
        """Your own effects that are listed, in the order they run."""
        rows = self.rows
        listed = [t for t in rows if rows[t].chk.isChecked()
                  or (t == self.selected and self.layer is None) or t in self.locked]
        return fxlayers.ordered(listed, self.panel._mix.get("order"))

    def _set_order(self, types: list[str]):
        order = list(dict.fromkeys(types))
        if order != self._order():
            self.panel._mix["order"] = order
            usage.used("voice-effect-reordered")
            self.panel.layers_changed()

    def _keys(self) -> list[tuple]:
        """What Your voice lists: ("fx", type), then ("layer", i) and ("lfx", i, type)."""
        keys: list[tuple] = [("fx", t) for t in self._order()]
        for i, d in enumerate(self._layers()):
            keys.append(("layer", i))
            keys += [("lfx", i, t) for t in fxlayers.ordered(
                (t for t in d["effects"] if t in voicefx.REGISTRY),
                self.panel._mix.get("order"))]
        return keys

    def _current(self) -> tuple:
        if self._layer() is not None:
            return ("lfx", self.layer, self.layer_fx) if self.layer_fx else ("layer", self.layer)
        return ("fx", self.selected)

    def sync(self):
        if self._syncing:
            return
        self._syncing = True
        try:
            rows = self.rows
            keys = self._keys()
            before = [_key(self.active.item(i)) for i in range(self.active.count())]
            if before != keys:
                self.active.blockSignals(True)
                self.active.clear()
                for k in keys:
                    item = QListWidgetItem()
                    item.setData(Qt.ItemDataRole.UserRole, "|".join(map(str, k)))
                    if k[0] == "lfx":   # a layer's effects: set in, and move with it
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDragEnabled)
                        item.setData(INDENT, 16)
                    self.active.addItem(item)
                self.active.blockSignals(False)
            current = self._current()
            for i in range(self.active.count()):
                item = self.active.item(i)
                k = _key(item)
                item.setText(self._item_text(k, rows))
                item.setIcon(self._item_icon(k))
                if k == current:
                    self.active.blockSignals(True)
                    self.active.setCurrentItem(item)
                    self.active.blockSignals(False)
            if not self.selected and self.layer is None and keys and keys[0][0] == "fx":
                self.selected = keys[0][1]
                self.active.setCurrentRow(0)
            n = sum(r.chk.isChecked() for r in rows.values())
            words = [ngettext("{n} effect on", "{n} effects on", n)]
            if self._layers():
                words.append(ngettext("{n} voice mixed in", "{n} voices mixed in",
                                      len(self._layers())))
            self.summary.setText(" · ".join(words))
            self.empty.setVisible(not keys)
            self._filter()
            self._build_settings()
            self._sync_controls()
        finally:
            self._syncing = False

    def _item_text(self, k: tuple, rows) -> str:
        if k[0] == "fx":
            row = rows[k[1]]
            status = _("On") if row.chk.isChecked() else _("Off")
            suffix = _("Locked") if k[1] in self.locked else ""
            return " · ".join(filter(None, (voicefx.shown(row.cls.name), status, suffix)))
        d = self._layers()[k[1]]
        if k[0] == "layer":   # (its icon says it's mixed in)
            if not d.get("on", True):
                return _("{voice} · off", voice=self.panel.layer_title(k[1]))
            return _("{voice} · {pct}%", voice=self.panel.layer_title(k[1]),
                     pct=round(d.get("amount", 1.0) * 100))
        cfg = d["effects"].get(k[2], {})
        status = _("On") if cfg.get("on") else _("Off")
        return " · ".join((voicefx.shown(voicefx.REGISTRY[k[2]].name), status))

    def _item_icon(self, k: tuple) -> QIcon:
        if k[0] == "layer":
            return icons.icon("shuffle", "accent_hi")
        t = k[-1]
        return icons.icon(FX_ICONS.get(t, "sliders"), "accent_hi" if k[0] == "fx" else "muted")

    def _dropped(self, *_args):
        """An item was dragged: your effects' order and the layers' order as listed now
        (a layer's effects stay with it)."""
        if self._syncing:
            return
        self.panel._flush()
        keys = [_key(self.active.item(i)) for i in range(self.active.count())]
        layers = [k[1] for k in keys if k[0] == "layer"]
        stack = self._layers()
        if layers != list(range(len(stack))):
            moved = [stack[i] for i in layers]
            if self.layer is not None and self.layer in layers:
                self.layer = layers.index(self.layer)
            stack[:] = moved
            usage.used("voice-layer-reordered")
        order = [k[1] for k in keys if k[0] == "fx"]
        if order != self._order():
            self.panel._mix["order"] = order
            usage.used("voice-effect-reordered")
        self.panel.layers_changed()
        QTimer.singleShot(0, self.sync)   # (after the view has finished the drop)

    def _move(self, step: int):
        """Move up / Move down: the selected effect, or layer, one place (an Undo
        step of its own)."""
        self.panel._flush()
        if self._layer() is not None:
            stack, i = self._layers(), self.layer
            assert i is not None
            j = i + step
            if 0 <= j < len(stack):
                stack[i], stack[j] = stack[j], stack[i]
                self.layer = j
                usage.used("voice-layer-reordered")
                self.panel.layers_changed()
            return
        order = [t for t in self._order() if t != "voice_output"]
        if self.selected not in order:
            return
        i = order.index(self.selected)
        j = i + step
        if 0 <= j < len(order):
            order[i], order[j] = order[j], order[i]
            self._set_order(order)

    # ------------------------------------------------------------------ add effects
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
        t = item.data(Qt.ItemDataRole.UserRole)
        row = self.rows[t]
        self.browser_hint.setText(voicefx.shown(row.cls.description))
        d = self._layer()
        if d is not None:
            self.add.setText(_("Edit effect") if t in d["effects"] else
                             _("Add to “{voice}”", voice=self.panel.layer_title(self.layer)))
        else:
            self.add.setText(_("Add another") if row.chk.isChecked() else _("Add effect"))
        self.add.setToolTip(_("Adds it again on top of your voice, so it plays twice")
                            if d is None and row.chk.isChecked() else "")

    def _add(self):
        item = self.browser.currentItem()
        if item is None:
            return
        t = item.data(Qt.ItemDataRole.UserRole)
        d = self._layer()
        duplicate = d is None and self.rows[t].chk.isChecked()
        if duplicate:
            # already in your voice: a second one, in the layer of extra effects
            stack = self._layers()
            extra = next((i for i, x in enumerate(stack) if not x.get("voice")), None)
            if extra is None:
                if len(stack) >= fxlayers.MAX_LAYERS:
                    self.browser_hint.setText(ngettext(
                        "You can mix in up to {n} voice. Remove one to add another.",
                        "You can mix in up to {n} voices. Remove one to add another.",
                        fxlayers.MAX_LAYERS))
                    return
                stack.append({"voice": "", "on": True, "amount": 1.0, "effects": {}})
                extra = len(stack) - 1
            self.layer, d = extra, stack[extra]
        if d is not None:
            if t not in d["effects"]:
                d["effects"][t] = {**voicefx.defaults(t), "on": True}
                usage.used("voice-effect-duplicated" if duplicate else "voice-effect-added")
            self.layer_fx = t
            self.panel.layers_changed()
        else:
            self.selected = t
            self.rows[t].chk.setChecked(True)
            usage.used("voice-effect-added")
        self.sync()
        if not self.wide:
            self.tabs.setCurrentIndex(2)

    def _pick(self, item, _previous=None):
        if self._syncing or item is None:
            return
        k = _key(item)
        if k[0] == "fx":
            self.selected, self.layer, self.layer_fx = k[1], None, ""
        else:
            self.layer, self.layer_fx = k[1], k[2] if k[0] == "lfx" else ""
        self._browse()
        self._build_settings()
        self._sync_controls()
        if not self.wide:
            self.tabs.setCurrentIndex(2)

    # ------------------------------------------------------------------ settings
    def _build_settings(self):
        d = self._layer()
        if d is not None:
            cls = voicefx.REGISTRY.get(self.layer_fx) if self.layer_fx else None
            key = ("layer", self.layer, self.layer_fx, id(d))
        else:
            row = self.rows.get(self.selected)
            cls = row.cls if row is not None else None
            key = (self.selected, id(row))
        if key == self._built_for:
            return
        self._built_for = key
        self._new_settings()
        if d is not None and not self.layer_fx:
            self._build_layer(d)
            return
        if cls is None:
            self.settings.addWidget(hint_label(_("Select an effect to change its settings.")))
            self.settings.addStretch(1)
            return
        self.settings.addWidget(section_label(voicefx.shown(cls.name)))
        if d is not None:
            where = hint_label(_("Part of “{voice}”, mixed in on top of your voice.",
                                 voice=self.panel.layer_title(self.layer)))
            where.setWordWrap(True)
            self.settings.addWidget(where)
        description = hint_label(voicefx.shown(cls.description))
        description.setWordWrap(True)
        self.settings.addWidget(description)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.enabled = QCheckBox(_("On"))
        actions.addWidget(self.enabled)
        actions.addStretch(1)
        reset = QPushButton(_("Reset"))
        reset.setProperty("quiet", True)
        actions.addWidget(reset)
        remove = QPushButton(_("Remove"))
        remove.setProperty("quiet", True)
        remove.clicked.connect(self._remove)
        actions.addWidget(remove)
        self.settings.addLayout(actions)
        if d is None:
            row = self.rows[self.selected]
            self.enabled.toggled.connect(row.chk.setChecked)
            reset.clicked.connect(row.reset)
            self._move_buttons()
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
        else:
            self.enabled.toggled.connect(self._layer_fx_on)
            reset.clicked.connect(self._layer_fx_reset)
        self.modified = hint_label("")
        self.settings.addWidget(self.modified)
        self.error = hint_label("")
        self.settings.addWidget(self.error)
        cfg = (d["effects"].get(self.layer_fx, {}) if d is not None
               else self.rows[self.selected].state())
        for q in cls.params:
            self._param(q, cfg.get(q.key, q.default))
        if d is None and self.selected == "backdrop":
            note = hint_label(_("Choose background sounds in Simple or the Effects menu."))
            note.setWordWrap(True)
            self.settings.addWidget(note)
        self.settings.addStretch(1)

    def _param(self, q, value):
        """One setting: its slider, with a box to type the exact number in."""
        control = ParamSlider(q, value, compact=False)
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

    def _move_buttons(self):
        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_up = QPushButton(_("Move up"))
        self.btn_up.clicked.connect(lambda: self._move(-1))
        self.btn_down = QPushButton(_("Move down"))
        self.btn_down.clicked.connect(lambda: self._move(1))
        row.addWidget(self.btn_up)
        row.addWidget(self.btn_down)
        row.addStretch(1)
        self.settings.addLayout(row)

    def _build_layer(self, d: dict):
        """A layer's own settings: on, how much of it you hear, where it is, remove."""
        title = self.panel.layer_title(self.layer)
        self.settings.addWidget(section_label(_("Mixed in: {voice}", voice=title)))
        about = hint_label(_("This voice plays on top of yours, after your own effects. "
                             "Pick one of its effects in Your voice to change it, or add "
                             "more to it from Add effects."))
        about.setWordWrap(True)
        self.settings.addWidget(about)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.enabled = QCheckBox(_("On"))
        self.enabled.toggled.connect(self._layer_on)
        actions.addWidget(self.enabled)
        actions.addStretch(1)
        remove = QPushButton(_("Remove"))
        remove.setProperty("quiet", True)
        remove.setToolTip(_("Remove “{voice}”", voice=title))
        remove.clicked.connect(self._remove)
        actions.addWidget(remove)
        self.settings.addLayout(actions)
        self._move_buttons()
        self.modified = hint_label("")
        self.error = hint_label("")
        self._param(voicefx.Param("amount", _("How much of it you hear"), 0, 1, 1, "", 0,
                                  (_("none"), _("all of it"))), d.get("amount", 1.0))
        self.settings.addStretch(1)

    def _sync_controls(self):
        d = self._layer()
        if d is not None:
            self._sync_layer(d)
            return
        row = self.rows.get(self.selected)
        if row is None:
            return
        cfg = row.state()
        for w, val in ((self.enabled, row.chk.isChecked()),
                       (self.lock, self.selected in self.locked)):
            w.blockSignals(True)
            w.setChecked(val)
            w.blockSignals(False)
        order = [t for t in self._order() if t != "voice_output"]
        movable = self.selected in order
        self.btn_up.setEnabled(movable and order.index(self.selected) > 0)
        self.btn_down.setEnabled(movable and order.index(self.selected) < len(order) - 1)
        target = self.panel.reset_target(self.selected) or {}
        self._show_values(row.cls, cfg, target)
        self.error.setText(row.err.text())
        self.error.setVisible(bool(row.err.text()))

    def _sync_layer(self, d: dict):
        if not self.layer_fx:
            self.enabled.blockSignals(True)
            self.enabled.setChecked(d.get("on", True))
            self.enabled.blockSignals(False)
            stack = self._layers()
            self.btn_up.setEnabled(bool(self.layer))
            self.btn_down.setEnabled(self.layer is not None and self.layer < len(stack) - 1)
            control, number = self.controls["amount"]
            for w in (control, number):
                w.blockSignals(True)
            control.set_value(d.get("amount", 1.0))
            number.setValue(d.get("amount", 1.0) * 100)
            for w in (control, number):
                w.blockSignals(False)
            return
        cls = voicefx.REGISTRY.get(self.layer_fx)
        cfg = d["effects"].get(self.layer_fx)
        if cls is None or cfg is None:
            return
        self.enabled.blockSignals(True)
        self.enabled.setChecked(bool(cfg.get("on")))
        self.enabled.blockSignals(False)
        self._show_values(cls, cfg, {})
        self.error.setVisible(False)

    def _show_values(self, cls, cfg: dict, target: dict):
        changed = []
        visibility = getattr(cls, "shown_when", {})
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

    @staticmethod
    def _scale(q):
        return 100 if 0 <= q.lo < q.hi <= 1 and not q.unit and q.step != 1 else 1

    def _number(self, key, value):
        self._write(key, value / self._scale(self.controls[key][0].q))

    def _write(self, key, value):
        d = self._layer()
        if d is not None:
            control = self.controls[key][0]
            value = control.q.clamp(value)
            if self.layer_fx:
                d["effects"][self.layer_fx][key] = value
            else:
                d["amount"] = value
            self.panel.layers_changed()
            self.schedule()
            return
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

    def _layer_on(self, on):
        d = self._layer()
        if d is not None:
            d["on"] = bool(on)
            self.panel.layers_changed()

    def _layer_fx_on(self, on):
        d = self._layer()
        if d is not None and self.layer_fx in d["effects"]:
            d["effects"][self.layer_fx]["on"] = bool(on)
            self.panel.layers_changed()

    def _layer_fx_reset(self):
        d = self._layer()
        if d is not None and self.layer_fx in d["effects"]:
            on = d["effects"][self.layer_fx].get("on", True)
            d["effects"][self.layer_fx] = {**voicefx.defaults(self.layer_fx), "on": on}
            self._built_for = None
            self.panel.layers_changed()

    def _remove(self):
        d = self._layer()
        if d is not None:
            if self.layer_fx:
                d["effects"].pop(self.layer_fx, None)
                self.layer_fx = ""
                if not d["effects"]:   # its last effect: the layer goes too
                    self.layer = None
            elif self.layer is not None:
                del self._layers()[self.layer]
                usage.used("voice-layer-removed")
                self.layer = None
            self._built_for = None
            self.panel.layers_changed()
            self.sync()
            return
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
