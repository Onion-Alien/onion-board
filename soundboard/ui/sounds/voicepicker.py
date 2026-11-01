"""Edit sound → Effects → Voice: pick the voice a sound is said in, from picture cards
(no names to remember). Three kinds, any of them together:

- My voice combos: your saved mixes (voicesetups), one click puts the whole mix on;
- Voice changer: the Voice tab's voices, Favorites and your own first;
- AI voice: the AI voices add-on's voices (only when it's installed).

The result is a soundfx voice ({"name", "effects", "ai"}), or {} for none."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QButtonGroup, QDialog, QGridLayout, QHBoxLayout, QInputDialog,
                               QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from soundboard.audio import soundfx
from soundboard.i18n import _
from soundboard.ui.kit import fit, icons
from soundboard.ui.kit.panel import Flow, card, hint_label
from soundboard.ui.voice.voicefxpanel import TILE_ART, TILE_MIN_W, VoiceTile

COLS = 4
FAVS, MINE, ALL = "favs", "mine", "all"


@dataclass
class Catalog:
    """What the picker shows. fx: (name, name as shown, effects, picture or None, one of
    your own?); ai: the add-on's voice dicts (id, name, emoji, ...); setups: (name,
    voice). The star callbacks keep the Voice tab's Favorites in step."""
    fx: list[tuple[str, str, dict, QIcon | None, bool]] = field(default_factory=list)
    fx_favs: list[str] = field(default_factory=list)
    ai: list[dict] = field(default_factory=list)
    ai_favs: list[str] = field(default_factory=list)
    ai_ready: bool = False
    setups: list[tuple[str, dict]] = field(default_factory=list)
    star_fx: Callable[[str, bool], None] = lambda _n, _on: None
    star_ai: Callable[[str, bool], None] = lambda _i, _on: None


def describe(voice: dict) -> str:
    """A voice in a few words: its name ("Robot + River", a setup's name)."""
    voice = soundfx.clean_voice(voice)
    if not voice:
        return _("No voice")
    return voice.get("name") or _("Custom")


class VoicePicker(QDialog):
    """`save_setup(name, voice)` keeps a mix as a setup and returns its name ("" if
    it couldn't). After exec(), `voice` is the pick."""
    KEEP_OPEN = True   # a click outside doesn't close it: it would lose work

    def __init__(self, cat: Catalog, current: dict, save_setup=None, parent=None):
        super().__init__(parent)
        fit.watch(self)
        self.setWindowTitle(_("Voice for this sound"))
        self.cat = cat
        self.save_setup = save_setup
        cur = soundfx.clean_voice(current)
        self._fx = cur.get("fx") or self._fx_name_for(cur)   # picked voice changer voice
        self._fx_effects = cur.get("effects", {}) if cur else {}
        self._ai = cur.get("ai") if cur else None  # picked AI voice {"id", "name", "pitch"}
        self._setup = cur.get("name", "") if cur.get("name") in dict(cat.setups) else ""
        self.voice = cur

        v = QVBoxLayout(self)
        self.summary = QLabel()
        self.summary.setObjectName("section")
        self.summary.setWordWrap(True)
        v.addWidget(self.summary)
        v.addWidget(hint_label(_("Click a card to put it on the sound, click it again to take "
                                 "it off. A voice changer voice and an AI voice can go on "
                                 "together.")))
        body = QWidget()
        self.page = QVBoxLayout(body)
        self.page.setContentsMargins(0, 0, 0, 0)
        self.page.setSpacing(10)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(body)
        v.addWidget(scroll, 1)

        self.setup_tiles: dict[str, VoiceTile] = {}
        if cat.setups:
            c, cv = card(_("My voice combos"), icon="star_filled")
            grid = self._grid(cv)
            for i, (name, voice) in enumerate(cat.setups):
                t = self._tile(name, self._setup_icon(voice), star=False)
                t.clicked.connect(lambda __=False, n=name: self._pick_setup(n))
                grid.addWidget(t, i // COLS, i % COLS)
                self.setup_tiles[name] = t
            self.page.addWidget(c)

        self.fx_tiles: dict[str, VoiceTile] = {}
        c, cv = card(_("Voice changer"), icon="voice")
        self.fx_chips = self._chips(cv, self._show_fx, bool(cat.fx_favs),
                                    any(m for *_x, m in cat.fx))
        self.fx_grid = self._grid(cv)
        for name, shown, _effects, pic, _mine in cat.fx:
            t = self._tile(shown, pic or icons.icon("sliders", "muted"))
            t.star.setChecked(name in cat.fx_favs)
            t.star.toggled.connect(lambda on, n=name: self._star_fx(n, on))
            t.clicked.connect(lambda __=False, n=name: self._pick_fx(n))
            self.fx_tiles[name] = t
        self.no_fx = hint_label(_("No favorites yet. Click the star in a voice's corner to "
                                  "keep it here."))
        cv.addWidget(self.no_fx)
        self.page.addWidget(c)

        self.ai_tiles: dict[str, VoiceTile] = {}
        c, cv = card(_("AI voice"), icon="speech")
        if cat.ai_ready and cat.ai:
            self.ai_chips = self._chips(cv, self._show_ai, bool(cat.ai_favs), False)
            self.ai_grid = self._grid(cv)
            from soundboard.ui.voice.aivoicepanel import voice_icon
            for vo in cat.ai:
                t = self._tile(vo["name"], voice_icon(vo))
                t.setToolTip(str(vo.get("description") or ""))
                t.star.setChecked(vo["id"] in cat.ai_favs)
                t.star.toggled.connect(lambda on, i=vo["id"]: self._star_ai(i, on))
                t.clicked.connect(lambda __=False, vo=vo: self._pick_ai(vo))
                self.ai_tiles[vo["id"]] = t
            self.no_ai = hint_label(_("No favorites yet. Click the star in a voice's corner to "
                                      "keep it here."))
            cv.addWidget(self.no_ai)
            cv.addWidget(hint_label(_("Said once in the AI voice when you save, then kept: it "
                                      "takes a few seconds, on your PC. Long songs aren't "
                                      "changed.")))
        else:
            self.ai_chips = {}
            cv.addWidget(hint_label(_("Get AI voices on the Voice tab (AI voices) first: then "
                                      "they're here too.")))
        self.page.addWidget(c)
        self.page.addStretch(1)

        row = QHBoxLayout()
        self.btn_use = QPushButton(_("Use it"))
        self.btn_use.setObjectName("primary")
        self.btn_use.setDefault(True)
        self.btn_use.clicked.connect(self.accept)
        row.addWidget(self.btn_use)
        self.btn_save = QPushButton(_("Save as a voice combo"))
        self.btn_save.setToolTip(_("Keep this mix under a name, to put it on other sounds "
                                   "with one click"))
        self.btn_save.clicked.connect(self._save)
        row.addWidget(self.btn_save)
        cancel = QPushButton(_("Cancel"))
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        row.addStretch(1)
        v.addLayout(row)
        self.btn_save.setVisible(save_setup is not None)
        self.resize(620, 680)

        self._show_fx(FAVS if cat.fx_favs else ALL)
        if self.ai_chips:
            self._show_ai(FAVS if cat.ai_favs else ALL)
        self._refresh()

    # ------------------------------------------------------------ building
    def _grid(self, lay) -> QGridLayout:
        g = QGridLayout()
        g.setSpacing(8)
        for c in range(COLS):
            g.setColumnStretch(c, 1)
        lay.addLayout(g)
        return g

    def _tile(self, title: str, pic, star: bool = True) -> VoiceTile:
        t = VoiceTile(title)
        if pic is not None:
            t.setIcon(pic)
            t.setProperty("art", True)
        t.setIconSize(QSize(TILE_ART, TILE_ART))
        t.setMinimumWidth(TILE_MIN_W)
        t.setCursor(Qt.CursorShape.PointingHandCursor)
        t.star.setVisible(star)
        return t

    def _chips(self, lay, show, favs: bool, mine: bool) -> dict[str, QPushButton]:
        w = QWidget()
        flow = Flow(w, gap=6)
        group = QButtonGroup(w)
        out = {}
        for key, text in ((FAVS, _("Favorites")), (MINE, _("Mine")), (ALL, _("All"))):
            if key == MINE and not mine:
                continue
            b = QPushButton(text)
            b.setObjectName("voicecat")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            if key == FAVS:
                icons.set_icon(b, "star_filled", "accent")
            b.clicked.connect(lambda __=False, k=key: show(k))
            group.addButton(b)
            flow.addWidget(b)
            out[key] = b
        lay.addWidget(w)
        return out

    @staticmethod
    def _place(grid: QGridLayout, tiles: dict, keys: list[str]):
        for t in tiles.values():
            grid.removeWidget(t)
            t.hide()
        for i, k in enumerate(keys):
            grid.addWidget(tiles[k], i // COLS, i % COLS)
            tiles[k].show()

    def _show_fx(self, key: str):
        self.fx_chips[key].setChecked(True)
        if key == FAVS:
            keys = [n for n in self.cat.fx_favs if n in self.fx_tiles]
        elif key == MINE:
            keys = [n for n, *_x, mine in self.cat.fx if mine]
        else:
            keys = list(self.fx_tiles)
        self._place(self.fx_grid, self.fx_tiles, keys)
        self.no_fx.setVisible(key == FAVS and not keys)

    def _show_ai(self, key: str):
        self.ai_chips[key].setChecked(True)
        keys = ([i for i in self.cat.ai_favs if i in self.ai_tiles] if key == FAVS
                else list(self.ai_tiles))
        self._place(self.ai_grid, self.ai_tiles, keys)
        self.no_ai.setVisible(key == FAVS and not keys)

    def _setup_icon(self, voice: dict):
        ai = voice.get("ai")
        if ai:
            vo = next((v for v in self.cat.ai if v["id"] == ai["id"]), None)
            if vo is not None:
                from soundboard.ui.voice.aivoicepanel import voice_icon
                return voice_icon(vo)
        name = voice.get("fx") or self._fx_name_for(voice)
        pic = next((p for n, _s, _e, p, _m in self.cat.fx if n == name), None)
        return pic or icons.icon("sliders", "muted")

    def _fx_name_for(self, voice: dict) -> str:
        effects = voice.get("effects") if voice else None
        return next((n for n, _s, e, _p, _m in self.cat.fx if effects and e == effects), "")

    # ------------------------------------------------------------ picking
    def _pick_setup(self, name: str):
        if self._setup == name:
            self._setup, self._fx, self._fx_effects, self._ai = "", "", {}, None
        else:
            voice = dict(self.cat.setups)[name]
            self._setup = name
            self._fx_effects = voice.get("effects", {})
            self._fx = (voice.get("fx") or self._fx_name_for(voice)) if self._fx_effects else ""
            self._ai = voice.get("ai")
        self._refresh()

    def _pick_fx(self, name: str):
        self._setup = ""
        if self._fx == name:
            self._fx, self._fx_effects = "", {}
        else:
            self._fx = name
            self._fx_effects = next(e for n, _s, e, _p, _m in self.cat.fx if n == name)
        self._refresh()

    def _pick_ai(self, vo: dict):
        self._setup = ""
        if self._ai and self._ai["id"] == vo["id"]:
            self._ai = None
        else:
            self._ai = {"id": vo["id"], "name": vo["name"], "pitch": 0.0}
        self._refresh()

    def _star_fx(self, name: str, on: bool):
        favs = self.cat.fx_favs
        if on and name not in favs:
            favs.append(name)
        elif not on and name in favs:
            favs.remove(name)
        self.cat.star_fx(name, on)

    def _star_ai(self, vid: str, on: bool):
        favs = self.cat.ai_favs
        if on and vid not in favs:
            favs.append(vid)
        elif not on and vid in favs:
            favs.remove(vid)
        self.cat.star_ai(vid, on)

    def _compose(self) -> dict:
        shown = next((s for n, s, *_x in self.cat.fx if n == self._fx), "")
        if self._setup:
            name = self._setup
        elif shown and self._ai:
            name = f"{shown} + {self._ai['name']}"
        else:
            name = shown or (self._ai["name"] if self._ai else "")
        return soundfx.clean_voice({"name": name, "fx": self._fx, "effects": self._fx_effects,
                                    **({"ai": self._ai} if self._ai else {})})

    def _refresh(self):
        self.voice = self._compose()
        for n, t in self.setup_tiles.items():
            t.setChecked(n == self._setup)
        for n, t in self.fx_tiles.items():
            t.setChecked(n == self._fx)
        for i, t in self.ai_tiles.items():
            t.setChecked(bool(self._ai) and i == self._ai["id"])
        self.summary.setText(_("This sound's voice: {voice}", voice=describe(self.voice))
                             if self.voice else _("No voice yet: pick one below"))
        self.btn_save.setEnabled(bool(self.voice))

    def _save(self):
        if not self.voice or self.save_setup is None:
            return
        name, ok = QInputDialog.getText(self, _("Save as a voice combo"), _("Name"),
                                        text=self.voice.get("name", ""))
        if not ok or not name.strip():
            return
        saved = self.save_setup(name, self.voice)
        if saved:
            self.cat.setups = [s for s in self.cat.setups if s[0] != saved] + [
                (saved, {**self.voice, "name": saved})]
            self._setup = saved
            self._refresh()
            self.summary.setText(_("Saved as “{name}”: it's under My voice combos here and on the "
                                   "Voice tab.", name=saved))
