"""Settings → Achievements (under Show advanced): every achievement as a tile, its badge
in its rarity's colour (the rare loading screens' colours), hidden ones as ??? until
earned. The counting is soundboard.core.achievements; this page only shows it.

A badge is Bun drawn in a scene for it (badges.py) unless a picture
for it is in assets/art/achievement-<id>.png (art.ART_DIR, which the installed build
carries): then that's shown, greyed while locked."""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QDateTime, QLocale, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QLabel, QLayout, QSizePolicy,
                               QVBoxLayout, QWidget)

from soundboard.core import achievements as ach
from soundboard.i18n import _
from soundboard.ui.kit import icons, theme
from soundboard.ui.kit.panel import hint_label
from soundboard.ui.settings import Page
from soundboard.ui.settings import badges
from soundboard.ui.settings.badges import TIER_SPLASH, tier_colour
from soundboard.ui.voice import art
from soundboard.ui.window.responsive import settled

TILE_W = 250   # the narrowest a tile gets; they share each row's width
BADGE = 56


def tier_name(tier: str) -> str:
    if tier in TIER_SPLASH:
        from soundboard.ui.bun import splash
        return splash.tier_name(TIER_SPLASH[tier])
    return _("Common")


def texts() -> dict[str, tuple[str, str]]:
    """Each achievement's name and what earns it."""
    return {
        "first_blood": (_("First Blood"), _("Play your first sound.")),
        "spammer": (_("Spammer"), _("Play 1,000 sounds.")),
        "menace": (_("Menace"), _("Play 10,000 sounds.")),
        "collector": (_("Collector"), _("Add 100 sounds.")),
        "hoarder": (_("Hoarder"), _("Add 250 sounds.")),
        "dragon_hoard": (_("Dragon's Hoard"), _("Add 1,000 sounds.")),
        "new_voice": (_("New Voice, Who Dis?"), _("Talk through the voice changer for 1 hour.")),
        "voice_actor": (_("Voice Actor"), _("Talk through the voice changer for 10 hours.")),
        "method_actor": (_("Method Actor"), _("Talk through the voice changer for 100 hours.")),
        "station_hopper": (_("Station Hopper"), _("Play 100 different radio stations.")),
        "radio_head": (_("Radio Head"), _("Play 1,000 different radio stations.")),
        "critic": (_("Critic"), _("Upvote 10 sounds in the Store.")),
        "tastemaker": (_("Tastemaker"), _("Upvote 100 sounds in the Store.")),
        "regular": (_("Regular"), _("Open Onion Board on 30 different days.")),
        "veteran": (_("Veteran"), _("Open Onion Board on 365 different days.")),
        "golden_bun": (_("Golden Bun"), _("See the Golden Bun loading screen.")),
        "ice_bun": (_("Ice Bun"), _("See the Ice Bun loading screen.")),
        "galaxy_bun": (_("Galaxy Bun"), _("See the Galaxy Bun loading screen.")),
        "rainbow_bun": (_("Rainbow Bun"), _("See the Rainbow Bun loading screen.")),
        "catch_em_all": (_("Full Set"), _("See the Golden, Ice and Galaxy Bun loading screens.")),
        "gamer_bun": (_("Gamer"), _("Beat Bun at Pong.")),
        "sore_loser": (_("Sore Loser"), _("Lose to Bun at Pong.")),
        "arcade_rat": (_("Arcade Rat"), _("Play all four of Bun's games.")),
        "rise_and_shine": (_("Rise and Shine"), _("Wake Bun up when he's asleep.")),
        "chatterbox": (_("Chatterbox"), _("Get Bun to talk 50 times.")),
        "who_hoots": (_("Who Hoots?"), _("Get Hoot to say something.")),
        "bun_mode": (_("Bun Mode"), _("Turn the mini player into Bun.")),
        "panic_button": (_("Panic Button"), _("Use Stop all 50 times.")),
        "silent_but_deadly": (_("Silent But Deadly"),
                              _("Play a sound with the sound volume at 0%.")),
        "gremlin": (_("3 AM Gremlin"), _("Play a sound between 3 and 4 in the morning.")),
        "pack_rat": (_("Pack Rat"), _("Add every free sound pack.")),
        "defector": (_("Defector"), _("Bring a board over from another soundboard.")),
        "clip_it": (_("Clip It"), _("Save a clip of what just played.")),
        "producer": (_("Producer"), _("Cut a program's sound in the clip editor.")),
        "link_grabber": (_("Link Grabber"), _("Add a sound from a link.")),
        "hotkey_hero": (_("Hotkey Hero"), _("Give 10 sounds a hotkey.")),
        "second_chances": (_("Second Chances"), _("Bring something back from Recently deleted.")),
        "mic_check": (_("Mic Check"), _("Record a sound of your own.")),
        "puppet_master": (_("Puppet Master"),
                          _("Send other programs' sound to others for 10 hours.")),
        "shapeshifter": (_("Shapeshifter"), _("Try 25 different voices.")),
        "mad_scientist": (_("Mad Scientist"), _("Save a voice of your own.")),
        "polyglot": (_("Polyglot"), _("Speak in another language.")),
        "robot_mouth": (_("Robot Mouth"), _("Make an AI voice of your own.")),
        "dice_roll": (_("Dice Roll"), _("Roll a random voice 20 times.")),
        "world_tour": (_("World Tour"), _("Play radio stations from 25 countries.")),
        "night_owl": (_("Night Owl"), _("Keep the radio on for 3 hours straight.")),
        "contributor": (_("Contributor"), _("Share a sound in the Store.")),
        "fashionista": (_("Fashionista"), _("Try 10 themes.")),
        "rainbow_road": (_("Rainbow Road"), _("Try every theme.")),
        "seasons": (_("Seasons"), _("Open Onion Board in every month of the year.")),
        "onion_onion": (_("Onion in an Onion"), _("Go online through Tor.")),
        "off_the_grid": (_("Off the Grid"), _("Switch on Offline mode.")),
        "remote_control": (_("Remote Control"), _("Play a sound from your phone.")),
        "streamer": (_("Streamer"), _("Have a chat command play a sound.")),
        "watcher": (_("Watcher"), _("Have an Onion Watch trigger go off.")),
        "no_life": (_("No Life"), _("Keep Onion Board open for 24 hours straight.")),
    }


@lru_cache(maxsize=128)
def _picture(ach_id: str, size: int, grey: bool) -> QPixmap | None:
    """assets/art/achievement-<id>.png in a circle, greyed while locked, or None."""
    path = art.ART_DIR / f"achievement-{ach_id}.png"
    if not path.is_file():
        return None
    img = QImage(str(path))
    if img.isNull():
        return None
    img = img.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                     Qt.TransformationMode.SmoothTransformation)
    if grey:
        img = img.convertToFormat(QImage.Format.Format_Grayscale8).convertToFormat(
            QImage.Format.Format_ARGB32)
    return QPixmap.fromImage(img)


class Badge(QWidget):
    """The achievement's badge: Bun in its scene (badges.py), in colour when earned,
    grey and faded while locked; a secret one still locked is a question mark in a ring
    of its rarity's colour. A picture in assets/art (achievement-<id>.png) wins."""

    def __init__(self, a: ach.Ach):
        super().__init__()
        self.a = a
        self.earned = False
        self.setFixedSize(BADGE, BADGE)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(2, 2, BADGE - 4, BADGE - 4)
        colour = tier_colour(self.a.tier)
        if self.a.hidden and not self.earned:   # a secret: ? in its rarity's ring
            circle = QPainterPath()
            circle.addEllipse(r)
            p.fillPath(circle, QColor(theme.tokens()["card_hi"]))
            g = 22
            p.drawPixmap(int((BADGE - g) / 2), int((BADGE - g) / 2),
                         icons.pixmap("question", g, theme.tokens()["faint"]))
            p.setPen(QPen(colour, 2.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(r)
        elif (pic := _picture(self.a.id, BADGE - 4, not self.earned)) is not None:
            circle = QPainterPath()
            circle.addEllipse(r)
            p.setClipPath(circle)
            p.drawPixmap(2, 2, pic)
        else:
            p.drawPixmap(0, 0, badges.badge(self.a.id, self.a.tier, BADGE, not self.earned,
                                            self.devicePixelRatioF()))
        p.end()


class Tile(QWidget):
    """One achievement: badge, name, what earns it, and its rarity with how far along
    it is or when it was earned; a bar along the bottom while it's on its way."""

    def __init__(self, a: ach.Ach, name: str, desc: str):
        super().__init__()
        self.a, self._name, self._desc = a, name, desc
        self.setObjectName("achtile")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        # Tab steps through the tiles (a screen reader reads each one's name and state)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 12, 12, 12)
        row.setSpacing(12)
        self.badge = Badge(a)
        # centred: every badge in a row at the same height, earned or not
        row.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignVCenter)
        col = QVBoxLayout()
        col.setSpacing(4)
        col.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.title = QLabel()
        self.title.setObjectName("section")
        self.title.setWordWrap(True)
        self.what = hint_label("")
        self.status = hint_label("")
        col.addWidget(self.title)
        col.addWidget(self.what)
        col.addWidget(self.status)
        row.addLayout(col, 1)
        self.fraction = 0.0
        self.refresh()

    def refresh(self):
        a = self.a
        when = ach.got(a.id)
        earned = bool(when)
        secret = a.hidden and not earned
        self.badge.earned = earned
        self.title.setText("???" if secret else self._name)
        self.what.setText(_("Hidden: keep playing to find it.") if secret
                          else self._desc)
        goal = ach.goal(a)
        have = min(ach.value(a.stat), goal)
        # the line under is only the rarity (a word, never a number beside it: "Common ·
        # 140 of 1,000" read as how many people had it); how far along is the bar, and
        # the numbers or the day it was earned are its tooltip
        line = tier_name(a.tier)
        if earned:
            tip = _("Earned {date}", date=QLocale().toString(
                QDateTime.fromSecsSinceEpoch(int(when)).date(), QLocale.FormatType.ShortFormat))
        elif secret or goal <= 1:
            tip = ""
        elif a.stat.endswith("_s"):
            tip = _("You're at {have} of {goal} hours",
                    have=QLocale().toString(have / 3600, "f", 1),
                    goal=QLocale().toString(int(goal // 3600)))
        else:
            tip = _("You're at {have} of {goal}", have=QLocale().toString(int(have)),
                    goal=QLocale().toString(int(goal)))
        self.status.setText(line)
        self.setToolTip(tip)
        self.fraction = 0.0 if earned or secret or goal <= 1 else have / goal
        self.setAccessibleName(f"{self.title.text()}. {self.what.text()} {line}. {tip}")
        self.badge.update()
        self.update()

    def focusInEvent(self, e):
        super().focusInEvent(e)
        self.update()

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self.update()

    def paintEvent(self, _e):
        tk = theme.tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        shape = QPainterPath()
        shape.addRoundedRect(r, 12, 12)
        p.fillPath(shape, QColor(tk["card_hi"]))
        if self.badge.earned:   # earned: washed and edged in the theme's highlight colour
            live = QColor(tk["live"])
            wash = QColor(live)
            wash.setAlphaF(0.16)
            p.fillPath(shape, wash)
            p.setPen(QPen(live, 1.5))
            p.drawRoundedRect(r.adjusted(0.75, 0.75, -0.75, -0.75), 11.5, 11.5)
        if self.hasFocus():   # the keyboard's ring
            p.setPen(QPen(QColor(tk["accent"]), 2))
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 11, 11)
        if self.fraction > 0:   # how far along: a thin bar in its rarity's colour
            p.setClipPath(shape)
            bar = QRectF(r.left(), r.bottom() - 4, r.width() * self.fraction, 4)
            p.fillRect(bar, tier_colour(self.a.tier))
        p.end()


class TileGrid(QWidget):
    """Tiles in as many equal columns as fit (each at least TILE_W), a row as tall as
    its tallest tile: no ragged rows, no empty strip down the right."""
    GAP = 8

    def __init__(self, tiles: list[Tile]):
        super().__init__()
        self.tiles = tiles
        self.shown = set(tiles)
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(self.GAP)
        # its columns never set its minimum width (three columns' minimum kept a page
        # that jumped narrower, an un-maximise, wider than its window): resizeEvent
        # takes them down to what fits
        self.grid.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.cols = 0
        self._place(1)   # (resizeEvent picks how many; a wider start would set the
                         # page's minimum width and keep it from ever getting narrow)

    def _place(self, cols: int, force: bool = False):
        if cols == self.cols and not force:
            return
        for t in self.tiles:
            self.grid.removeWidget(t)
        for c in range(max(cols, self.cols)):
            self.grid.setColumnStretch(c, 1 if c < cols else 0)
        self.cols = cols
        shown = [t for t in self.tiles if t in self.shown]
        for i, t in enumerate(shown):
            self.grid.addWidget(t, i // cols, i % cols)
        for t in self.tiles:
            t.setVisible(t in self.shown)
        self.updateGeometry()

    def show_only(self, tiles) -> int:
        """Show just `tiles` (the filters' picks), closed up; how many there are."""
        self.shown = set(tiles) & set(self.tiles)
        self._place(self.cols, force=True)
        return len(self.shown)

    def minimumSizeHint(self):
        return QSize(TILE_W, self.grid.minimumSize().height())

    def sizeHint(self):
        return QSize(TILE_W, self.grid.sizeHint().height())

    def resizeEvent(self, e):
        w = e.size().width()
        self._place(max(1, (w + self.GAP) // (TILE_W + self.GAP)))
        super().resizeEvent(e)


class _Shown(QWidget):
    """The page, calling `on_show` each time it's shown."""

    def __init__(self, on_show):
        super().__init__()
        self._on_show = on_show

    def showEvent(self, e):
        self._on_show()
        super().showEvent(e)


class AchievementsPage(Page):
    def _achievements(self):
        w = _Shown(self.refresh)
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 16, 12)   # (as SettingsDialog._page's)
        v.setSpacing(12)
        ach.sounds_now(len(self.mw.cfg.sounds))   # (sounds added since the last tick)
        words = texts()
        self.dlg.ach_tiles = []
        self.dlg.ach_cards = []
        v.addWidget(self._filters())
        for hidden, title, hint, icon in (
                (False, _("Achievements"), "", "trophy"),
                (True, _("Secret achievements"),
                 _("Hidden until you find them. The ring says how rare each one is."), "question")):
            card, cv = self._card(title, hint, icon=icon)
            if not hidden:
                self.dlg.ach_count = hint_label("")
                cv.addWidget(self.dlg.ach_count)
                self._popup_options(cv)
            tiles = [Tile(a, *words[a.id]) for a in ach.ALL if a.hidden == hidden]
            self.dlg.ach_tiles += tiles
            grid = TileGrid(tiles)
            cv.addWidget(grid)
            v.addWidget(card)
            self.dlg.ach_cards.append((card, grid))
        self.dlg.ach_none = hint_label(_("Nothing here yet. Try another filter."))
        self.dlg.ach_none.hide()
        v.addWidget(self.dlg.ach_none)
        v.addStretch(1)
        self._count()
        return w

    def _popup_options(self, cv):
        """Whether an earned one pops up at all, and whether that pop-up plays its chime
        (no pop-up, no chime: that box waits greyed until the pop-ups are back on)."""
        mw = self.mw
        pops = self._option(cv, _("Show pop-ups"),
                            _("\"Achievement unlocked\" at the bottom of the screen when you "
                              "earn one."),
                            mw.cfg.achievement_popups,
                            lambda b: (mw.set_option("achievement_popups", b),
                                       sound.setEnabled(b)))
        sound = self._option(cv, _("Pop-up sound"),
                             _("Play a chime in your headphones when you earn one."),
                             mw.cfg.achievement_sound,
                             lambda b: mw.set_option("achievement_sound", b))
        sound.setEnabled(mw.cfg.achievement_popups)
        self.dlg.box_ach_popups, self.dlg.box_ach_sound = pops, sound

    # the filters: which ones (all, earned, not yet) and which rarity
    SHOW = ("all", "earned", "todo")

    def _filters(self) -> QWidget:
        from PySide6.QtWidgets import QButtonGroup, QComboBox, QPushButton
        from soundboard.ui.kit.panel import Flow
        from soundboard.ui.kit.wheelguard import no_wheel
        row = QWidget()
        flow = Flow(row, gap=8)
        group = QButtonGroup(row)
        group.setExclusive(True)
        self.dlg.ach_show = {}
        for key, words in zip(self.SHOW, (_("All"), _("Earned"), _("Not yet"))):
            b = QPushButton(words)
            b.setObjectName("voicetab")   # (the page-tab chips: checkable, one at a time)
            b.setCheckable(True)
            b.setChecked(key == "all")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(self.apply_filters)
            group.addButton(b)
            flow.addWidget(b)
            self.dlg.ach_show[key] = b
        rarity = QComboBox()
        rarity.setAccessibleName(_("Rarity"))
        rarity.addItem(_("Every rarity"), "")
        for tier in ach.TIERS:
            rarity.addItem(tier_name(tier), tier)
        no_wheel(rarity)
        rarity.currentIndexChanged.connect(self.apply_filters)
        flow.addWidget(rarity)
        self.dlg.ach_rarity = rarity
        return row

    def apply_filters(self, *_):
        """Show only what the filters pick; a section with none of it goes, and a
        line says so when nothing at all is left."""
        show = next((k for k, b in self.dlg.ach_show.items() if b.isChecked()), "all")
        tier = self.dlg.ach_rarity.currentData() or ""
        left = 0
        # painted once, closed up: a frame of the old, tall card with a few tiles at its
        # bottom showed between
        with settled(self.dlg):
            for card, grid in self.dlg.ach_cards:
                picked = [t for t in grid.tiles
                          if (not tier or t.a.tier == tier)
                          and (show == "all" or (show == "earned") == bool(ach.got(t.a.id)))]
                n = grid.show_only(picked)
                card.setVisible(bool(n))
                left += n
            self.dlg.ach_none.setVisible(not left)

    def _count(self):
        n, total = ach.earned(), len(ach.ALL)
        self.dlg.ach_count.setText(_("{n} of {total} earned. The badge's colour is its "
                                     "rarity, like the rare loading screens.", n=n, total=total))

    def refresh(self):
        """Fresh numbers each time the page is shown (they move while the app runs)."""
        from shiboken6 import isValid
        for t in getattr(self.dlg, "ach_tiles", ()):
            if isValid(t):
                t.refresh()
        if isValid(self.dlg.ach_count):
            self._count()
            self.apply_filters()   # (one may have been earned meanwhile)
