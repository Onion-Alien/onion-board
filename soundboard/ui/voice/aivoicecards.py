"""The AI voices card's voice cards: their pictures, chips, favorites, cards / list view
and the bar under the voice that's on (Edit voice). Mixed into AiVoicePanel
(aivoicepanel.py)."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QBoxLayout, QDialog, QLabel, QMenu, QPushButton, QVBoxLayout,
                               QWidget)

from soundboard.core import usage
from soundboard.i18n import _
from soundboard.speech import aivoicelist as avl
from soundboard.ui.voice import art
from soundboard.ui.kit import fit, icons
from soundboard.ui.voice.aivoicebrowser import HEAR, mine_icon
from soundboard.ui.voice.effectspopup import place_over
from soundboard.ui.voice.groupbar import no_match
from soundboard.ui.voice.voicetiles import place_bar_controls
from soundboard.ui.voice.voicefxpanel import (LIST_MIN_W, MAX_COLS, PICKED_ART, TILE_ART,
                                              TILE_GAP, TILE_MIN_W, VoiceTile)

if TYPE_CHECKING:
    from soundboard.ui.voice.aivoicepanel import AiVoicePanel

    class _Panel(QWidget):
        # what AiVoicePanel itself provides, for the type checker only
        def __getattr__(self, name: str) -> Any: ...
else:
    _Panel = object


# the chips over the voice cards: All shows a heading per kind (avl.who), your own
# first (under the long ready-made grid, the ones you recorded were out of sight)
ALL, FAVS, MINE = "", "favs", "mine"
MAKE = "+make"   # the Make your own voice card's place among the voice ids
KINDS = ((MINE, _("Mine")), ("men", _("Men")), ("women", _("Women")),
         ("other", _("In between & fun")))
KIND_ICONS = {"men": "voice", "women": "voice", "other": "laugh", MINE: "mic"}


def voice_kind(voice: dict) -> str:
    """The heading a voice card goes under: yours under Mine, else who it sounds like."""
    return MINE if avl.is_mine(voice) else avl.who(voice)


def emoji_icon(emoji: str, size: int = TILE_ART) -> QIcon:
    """A voice's emoji as a card picture (the AI voices have emoji, not drawings)."""
    pm = QPixmap(size * 2, size * 2)   # drawn at 2x: sharp on a high-DPI screen too
    pm.setDevicePixelRatio(2.0)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    f = QFont("Segoe UI Emoji")
    f.setPixelSize(int(size * 0.8))
    p.setFont(f)
    p.drawText(0, 0, size, size, Qt.AlignmentFlag.AlignCenter, emoji or "🎙️")
    p.end()
    return QIcon(pm)


def art_key(voice: dict) -> str:
    """A built-in AI voice's picture in assets/art: "ai-voice-bear" (yours have none)."""
    return "" if avl.is_mine(voice) else "ai-voice-" + art.slug(str(voice.get("id", "")))


def voice_icon(voice: dict, size: int = TILE_ART) -> QIcon:
    """A voice's card picture: its drawing (ui/voice/art.py) when there is one, else its
    emoji; one of yours, the picture you picked or My own mix's."""
    if avl.is_mine(voice):
        return mine_icon(voice) or emoji_icon(str(voice.get("emoji") or ""), size)
    key = art_key(voice)
    pic = art.icon(key) if key else None
    return pic or emoji_icon(str(voice.get("emoji") or ""), size)


class EditPopup(QDialog):
    """An AI voice's Edit voice: its pitch, over the voice bar's button (like the
    voice changer's Effects pop-up)."""

    def __init__(self, panel: AiVoicePanel):
        # owned by the app's window: inside a card the theme makes every widget
        # see-through (QFrame#card QWidget), a pop-up's background too
        super().__init__(panel.window(), Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        fit.watch(self)
        self.setProperty("popover", True)
        self.setObjectName("transport")
        self.setAccessibleName(_("Edit voice"))
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 14)
        v.setSpacing(10)
        title = QLabel(_("Edit voice"))
        title.setObjectName("section")
        title.setProperty("head", True)
        v.addWidget(title)
        v.addWidget(panel.pitch_box)
        panel.pitch_box.show()
        self.setFixedWidth(400)

    def open_for(self, under: QWidget):
        self.adjustSize()
        place_over(self, under)
        self.show()


class AiVoiceCards(_Panel):
    """AiVoicePanel's voice cards and the voice bar."""

    def _mark_tile(self):
        """Light up the picked voice's card only while the AI voice is on (like the
        voice changer's cards): off, no card looks switched on."""
        vid = self.current_voice() if self.is_on() else None
        self.tiles.setExclusive(False)
        for i, b in self._tile.items():
            b.setChecked(i == vid)
        self.tiles.setExclusive(True)

    # ------------------------------------------------------------ the voice cards
    def _fill_tiles(self):
        """(Re)make a card for each voice the add-on has."""
        for b in self._tile.values():
            self.tiles.removeButton(b)
            self._tile_grid.removeWidget(b)
            b.hide()   # until it's gone it would paint over the regrown grid
            b.deleteLater()
        self._tile = {}
        for vo in self.voices:
            vid = vo["id"]
            b = VoiceTile(vo["name"])
            if self._listed:
                b.set_listed(True)
            b.setIcon(voice_icon(vo))
            b.setIconSize(QSize(TILE_ART, TILE_ART))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            tags = avl.tag_line(vo)
            about = str(vo.get("about") or vo.get("description") or "")
            b.setToolTip(f"{tags}. {about}" if tags and about else tags or about)
            b.clicked.connect(lambda __=False, i=vid: self._tile_clicked(i))
            b.star.setChecked(vid in self._favs)
            b.star.toggled.connect(lambda on, i=vid: self.set_favorite(i, on))
            b.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            b.customContextMenuRequested.connect(
                lambda pos, i=vid, w=b: self._card_menu(i, w.mapToGlobal(pos)))
            self.tiles.addButton(b)
            self._tile[vid] = b
        self._place_tiles()
        self._show_about()

    def _place_tiles(self):
        """The cards the picked chip shows: All under a heading per kind (lowest voice
        first), else one kind (or your favorites, in the order you starred them)."""
        g, cols = self._tile_grid, self._tile_cols
        for w in (*self._tile.values(), *self._heads.values(), self.make_tile):
            g.removeWidget(w)
        by_id = {vo["id"]: vo for vo in self.voices if vo["id"] in self._tile}
        low_first = sorted(by_id.values(), key=lambda vo: vo.get("pitch_hz", 0))
        rows: list[tuple[str, list[str]]]
        if self._group == ALL:
            rows = [(k, [vo["id"] for vo in low_first if voice_kind(vo) == k])
                    for k, _t in KINDS]
        elif self._group == FAVS:
            rows = [("", [i for i in self._favs if i in by_id])]
        else:
            rows = [("", [vo["id"] for vo in low_first if voice_kind(vo) == self._group])]
        found = self.bar.text()
        if found:
            rows = [(k, [i for i in ids if self.bar.matches(self._tile[i].title, i)])
                    for k, ids in rows]
        # Make your own voice: the last card under Mine (and in Mine), even with none yet
        make = not found and self._group in (ALL, MINE)
        if make:
            rows = [(k, ids + [MAKE] if k == MINE or self._group == MINE else ids)
                    for k, ids in rows]
        shown: set[str] = set()
        r = 0
        for head, group in rows:
            if not group:
                continue
            if head:
                g.addWidget(self._heads[head], r, 0, 1, cols)
                r += 1
            for i, vid in enumerate(group):
                g.addWidget(self._tile.get(vid) or self.make_tile, r + i // cols, i % cols)
            r += (len(group) + cols - 1) // cols
            shown.update(group)
        for k, lbl in self._heads.items():
            lbl.setVisible(self._group == ALL and any(
                (MINE if i == MAKE else voice_kind(by_id[i])) == k for i in shown))
        for vid, b in self._tile.items():
            b.setVisible(vid in shown)
        self.make_tile.setVisible(make)
        self.no_favs.setVisible(self._group == FAVS and not shown and not found)
        no_match(self.no_match, found, shown)
        for c in range(MAX_COLS):
            g.setColumnStretch(c, 1 if c < cols else 0)

    def show_group(self, key: str):
        """Show one chip's voices (ALL, FAVS, MINE or an avl.WHO key)."""
        self._group = key
        self.bar.set_group(key)
        self._place_tiles()

    def _group_count(self, key: str) -> int:
        """How many voices a group holds (the dropdown's numbers)."""
        listed = [vo for vo in self.voices if vo["id"] in self._tile]
        if key == ALL:
            return len(listed)
        if key == FAVS:
            return sum(i in self._tile for i in self._favs)
        return sum(voice_kind(vo) == key for vo in listed)

    @property
    def favorites(self) -> list[str]:
        return list(self._favs)

    def set_favorite(self, vid: str, on: bool):
        """Star or unstar a voice: Favorites lists them in the order you starred them."""
        if on == (vid in self._favs):
            return
        if on:
            usage.used("ai-voice-favorite")   # the name only (usage.py)
            self._favs.append(vid)
        else:
            self._favs.remove(vid)
        b = self._tile.get(vid)
        if b is not None and b.star.isChecked() != on:
            b.star.setChecked(on)   # (toggled comes back here and finds nothing to do)
        if self._group == FAVS:
            self._place_tiles()
        self._emit()

    def _fit_width(self, width: int):
        """As many voice cards a row as the width holds, at least one."""
        least = LIST_MIN_W if self._listed else TILE_MIN_W
        cols = max(1, min(MAX_COLS, (width + TILE_GAP) // (least + TILE_GAP)))
        if cols != self._tile_cols:
            self._tile_cols = cols
            self._place_tiles()

    def set_view(self, view: str):
        """Picture cards, or a list (the voice changer's switch: the Voice tab keeps
        the two the same)."""
        self._listed = view == "list"
        self.view_toggle.set_view(view)
        for b in (*self._tile.values(), self.make_tile):
            b.set_listed(self._listed)
        self._tile_cols = 0   # refit for the new width a voice needs
        self._fit_width(self.width())

    # ------------------------------------------------------------ the voice bar
    def show_picked_row(self, room: bool | None = None):
        """The bar under the cards shows only while the AI voice is on, as the voice
        changer's does. `room`: whether the Voice tab has a place for it now (its own
        tab showing)."""
        if room is not None:
            self._picked_room = room
        self.picked.setVisible(getattr(self, "_picked_room", True)
                               and (self.is_on() or getattr(self, "_paused", False)))

    def set_paused(self, paused: bool):
        """Paused from its bar (or by the Voices switch): the bar stays, dimmed, with its
        play button to bring the voice back (VoicePanel._show_bar_controls)."""
        self._paused = paused
        self.show_picked_row()

    def _bar_extra(self) -> int:
        """The width of the bar's pause and ✕ (the Voice tab adds them), and a gap."""
        ctl = getattr(self, "bar_controls", None)
        return ctl.sizeHint().width() + self.picked_box.spacing() if ctl is not None else 0

    def _fit_picked(self):
        """The buttons beside the voice's name while they fit there, else on a line of
        their own under it (where they wrap, narrow)."""
        if not hasattr(self, "_picked_btns"):
            return
        box = self.picked_box
        btns = [b for b in self._picked_btns.findChildren(QPushButton) if not b.isHidden()]
        need = (sum(b.sizeHint().width() for b in btns) + 10 * max(0, len(btns) - 1))
        m = box.contentsMargins()
        line = self.picked.width() - m.left() - m.right() - self._bar_extra()
        beside = (line - PICKED_ART - min(self.picked_name.sizeHint().width(), 140)
                  - self.picked_kind.sizeHint().width() - 3 * box.spacing())
        want = (QBoxLayout.Direction.LeftToRight if need <= beside
                else QBoxLayout.Direction.TopToBottom)
        if box.direction() != want:
            box.setDirection(want)
        place_bar_controls(self)
        # beside the name they keep one line (half the bar was too little for all of
        # them, so they wrapped); under it they wrap when they must
        self._picked_btns.setMinimumWidth(
            need if want == QBoxLayout.Direction.LeftToRight else 0)

    def open_tweak(self, under: QWidget | None = None):
        """Edit voice: the pitch, in a pop-up over the bar's button (or `under`)."""
        if self.tweak_pop is None:
            # self is the AiVoicePanel this mixin is part of
            self.tweak_pop = EditPopup(self)  # pyright: ignore[reportArgumentType]
        self.tweak_pop.open_for(under if under is not None else self.btn_tweak)

    def _card_menu(self, vid: str, pos: QPoint):
        """A voice card's right-click menu, as the voice changer's: Hear it, Edit voice,
        its hotkey, and for one of your own voices change and delete."""
        from soundboard.ui.kit.hotkeypick import pretty_key
        vo = next((v for v in self.voices if v["id"] == vid), None)
        if vo is None:
            return
        m = QMenu(self)
        if self.previewer.available():
            m.addAction(icons.icon("headphones"), HEAR, lambda: (
                usage.used("ai-voice-hear"),
                self.previewer.hear(self.b_hear, vo, self._sampled, self._say)))
            m.addSeparator()
        m.addAction(icons.icon("sliders"), _("Edit voice…"), lambda: self.edit_voice(vid))
        key = self.keys.get(vid, "")
        m.addAction(icons.icon("keyboard"),
                    _("Hotkey: {key}…", key=pretty_key(key)) if key else _("Set a hotkey…"),
                    lambda: self.hotkey_asked.emit(vid))
        if key:
            m.addAction(icons.icon("close"), _("Clear hotkey"),
                        lambda: self.hotkey_cleared.emit(vid))
        if avl.is_mine(vo):
            m.addSeparator()
            if self.can_make():
                m.addAction(icons.icon("edit"), _("Change this voice"), lambda: self.edit(vid))
            m.addAction(icons.icon("trash", "danger_text"), _("Delete"),
                        lambda: self.delete(vid))
        m.exec(pos)

    def edit_voice(self, vid: str):
        """A card's Edit voice: that voice picked, and its pitch pop-up over the card."""
        usage.used("ai-voice-edit-menu")
        self.pick(vid)
        self.open_tweak(self._tile.get(vid))

    def _tile_clicked(self, vid: str):
        """A voice card: that voice, on; the one that's on already: off (as the voice
        changer's cards)."""
        if self.is_on() and vid == self.current_voice():
            self.stop()
            return
        self.use(vid)

    def use(self, vid: str):
        """A card was clicked: that voice, on now (like the voice changer's cards)."""
        self.pick(vid)
        if vid in self._tile and not self.is_on():
            self.b_start.setChecked(True)      # _toggle starts it with this voice

    def pick(self, vid: str):
        """Make this the voice: the next Start, or now if it's on."""
        if vid not in self._tile:
            return
        self.s["voice"] = vid
        self._show_about()
        if self.ctl.running:
            # (still loading: it's used once it's ready; until then "starting…" stays,
            # as the backup voice is what others hear)
            self.ctl.set_voice(vid, self.s["pitch"])
            self._voice_name = self._voice().get("name", "")
            if self._status == "on":
                self._state(_("● switching to {voice}…", voice=self._voice_name))
        self._emit()
