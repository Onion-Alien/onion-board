"""The main window fitting its size: what gives way as it gets narrower or shorter (the
rail, the mixer, the category bar, the Setup page's columns, the toolbar), the mini player
below its size (with as many pads as fit), and laying it all out again after a change.

MainWindow makes one ``FitControl`` (``MainWindow.fitctl``); everything here runs on the UI
thread."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QBoxLayout, QWidgetItem

from soundboard.core import achievements
from soundboard.ui.window import responsive
from soundboard.ui.kit import toast as toastmod
from soundboard.ui.window.controller import Controller
from soundboard.ui.kit.widgets import SLIM_PAD_H, pad_height, take_out

if TYPE_CHECKING:
    from soundboard.ui.window.mainwindow import MainWindow

log = logging.getLogger(__name__)

BODY_SIDE = 14         # the gap around the window's content (beside the tab rail too)...
BODY_SIDE_TIGHT = 8    # ...and beside the rail in a narrow window
MINI_SIZE = QSize(440, 380)   # below this the window becomes the mini player...
MINI_PAD_ROWS = 1             # ...which has the pads above it when this many rows fit
SEARCH_MIN_W = 220    # the Sounds tab's search box, until the window gets narrow
SEARCH_TIGHT_W = 130  # ...then this, until it gets very narrow
# ...and its most: a few words go in it, so past this it's only a longer empty bar
# (456 px at 1180x720, so normal windows are unchanged). The seek bar, the levels and
# the drop box still follow the window: wider is useful there.
SEARCH_MAX_W = 480


class FitControl(Controller):
    """The size and fit of one MainWindow (``mw``)."""

    def __init__(self, mw: MainWindow):
        super().__init__(mw)
        # what gave way with Setup showing and without, at one window size (_fit_setup_tab)
        self._tab_fits: dict = {}

    def _init_fit(self):
        """What gives way when the window gets small (see ui/window/responsive.py). Lower
        numbers go first; width and height are handled separately."""
        mw = self.mw
        r = responsive
        f = self._fit = r.Fitter(mw._full)
        self._results_open = False      # web results are taking the pads' place
        self._cat_bar_compact = False   # the fitter's last say on the category bar
        # last: opened out, the rail stays open until nothing else can give (it shut
        # again at once when opened in a mid-sized window)
        f.add(90, "w", self._squeeze_rail)
        # the Sounds toolbar's steps (bar_step): the search box beside them must never
        # grow as the window narrows, see size_search below
        bar_tight: set[int] = set()
        self._bar_steps = []   # (search_button_changed)

        def bar_step(step: int, apply):
            def run(tight: bool):
                (bar_tight.add if tight else bar_tight.discard)(step)
                apply(tight)
                size_search()
            self._bar_steps.append((step, "w", run))
            return run

        def size_search():
            """The search box keeps room to type in until the buttons beside it have
            shrunk, then some room ("Search..." was all that was left once their words
            came back beside a box allowed down to nothing), and only at the very
            narrowest none. And it never grows as the window narrows: the room a button's
            words (or the card size) gave up went to the box, so a narrower window had a
            wider box. Once anything beside it has given way it stops at the size it had
            then, and the spare room goes after the search button, as past SEARCH_MAX_W."""
            low = (0 if 66 in bar_tight else SEARCH_TIGHT_W if 62 in bar_tight
                   else SEARCH_MIN_W)
            # the search button's steps gave nothing up while it's away (Offline mode)
            gave = bar_tight - ({17, 63} if not mw.ytresults.available() else set())
            most = (SEARCH_MAX_W if not gave else SEARCH_TIGHT_W
                    if gave & {63, 64, 65} else SEARCH_MIN_W)
            mw.search.setMinimumWidth(low)
            mw.search.setMaximumWidth(max(low, most))
            r.touch(mw.search)

        f.add(10, "w", bar_step(10, mw.padctl._fit_size_picker))
        f.add(17, "w", bar_step(17, r.icon_only(mw.btn_yt)))   # "Search online": its words first
        f.add(18, "w", bar_step(18, r.icon_only(mw.btn_view)))   # its tooltip says what it is
        # cards / list: only the other view's icon, one click away
        f.add(19, "w", bar_step(19, lambda tight: (mw.pad_view_toggle.set_compact(tight),
                                                   r.touch(mw.pad_view_toggle))))
        # the label and the dropdown go together: a lone "Clean" said nothing (the full
        # picker is on the Setup tab)
        # the ear button shrinks to its icon first: the level bar is the live part
        f.add(12, "w", r.icon_only(mw.btn_check))
        f.add(14, "w", mw._show_np_time)   # also hidden while it's blank
        f.add(45, "w", r.hide(mw.speed_btn))
        f.add(30, "w", r.hide(mw.chk_monitor))
        # the levels strip never drops a group: one is shown whole and the other two
        # become icons that bring theirs up (_fit_mixer)
        f.add(52, "w", self._fit_mixer)
        f.add(40, "w", r.hide(*mw._transport_vol))
        f.add(50, "w", r.hide(mw.np_name))
        f.add(60, "w", bar_step(60, r.icon_only(mw.btn_add)))
        f.add(62, "w", bar_step(62, lambda tight: None))   # the box down to SEARCH_TIGHT_W
        # very narrow: the search button (and its site menu) goes; Enter still searches
        # the site picked last
        f.add(63, "w", bar_step(63, lambda tight: (
            mw.btn_yt.setVisible(not tight and mw.ytresults.available()),
            r.touch(mw.btn_yt))))
        f.add(64, "w", bar_step(64, r.icon_only(mw.btn_more)))
        # the very narrowest: the cards / list switch steps aside too (as the search
        # button does), before the box gives up the last of its room; the mini player
        # is only a little further
        f.add(65, "w", bar_step(65, r.hide(mw.pad_view_toggle)))
        f.add(66, "w", bar_step(66, lambda tight: None))   # the box down to nothing
        mw._radio_steps = mw.radio.fit_steps()   # swapped with the tab (Privacy)
        f.extend(mw._radio_steps)
        self._tab_steps = {k: getattr(mw, k).fit_steps() for k in ("voice", "triggers")}
        for steps in self._tab_steps.values():
            f.extend(steps)
        # height: the whole mixer strip
        f.add(5, "h", mw.rail.compact)   # the rail's buttons closer together, first
        f.add(40, "h", lambda tight: r.hide(mw.mixer)(
            tight and (mw.height() < 520 or mw.width() < 760)))
        f.add(50, "h", self._cat_bar_step)   # the overlay's category key still works
        self._stack_cols = (self._stack_setup,
                            *mw.voice.stack_steps())
        mw.setMinimumSize(responsive.MIN_SIZE)

    def search_button_changed(self):
        """The search button came or went (Offline mode): the toolbar's steps are tried
        again, so the room it gave up brings back what fits (the card size), and the
        search box is sized for what's beside it now."""
        if not hasattr(self, "_fit"):
            return   # (before _init_fit: the first fit sizes it all)
        self._fit.retry(self._bar_steps)
        self._refit()

    def live(self, dragging: bool):
        """The window's edge is being dragged (MainWindow.nativeEvent): each step fits
        with the sizes Qt has cached, and letting go fits once more measuring it all
        fresh, as every step did before (~3-10 ms a step, most on Setup and Voice)."""
        fit = getattr(self, "_fit", None)
        if fit is None or fit.live == dragging:
            return
        fit.live = dragging
        if not dragging:
            self._refit()

    def _cat_bar_step(self, compact: bool):
        """The fitter's say on the category bar: it hides it when the window is short."""
        self._cat_bar_compact = compact
        self._sync_cat_bar()

    def _sync_cat_bar(self):
        """The category bar is hidden when the window is short (the fitter) or when web
        results take the pads' place: leaving its empty row in the layout kept a gap
        between the toolbar and the results' buttons."""
        mw = self.mw
        mw.cat_bar.setVisible(not self._cat_bar_compact and not self._results_open)
        responsive.touch(mw.cat_bar)

    def _refit(self):
        mw = self.mw
        if getattr(self, "_refitting", False):
            return
        self._refitting = True
        try:
            with responsive.hold_updates(mw):
                self._refit_layout()
        finally:
            self._refitting = False
        self._note_side()

    def _key(self) -> tuple:
        """What a kept side (_tab_fits) is good for: this window size (the pages' changes
        with the tab: the transport bar), these steps."""
        mw = self.mw
        return (mw.width(), mw.height(), self._fit.changes)

    def _note_side(self):
        """What gives way now, kept for the side showing (Setup or not), unless a tab
        switch is half-way (the tab showing isn't the one fitted for yet)."""
        mw = self.mw
        if (not hasattr(self, "_fit")
                or getattr(mw, "_fit_tab", None) is not mw.tabs.currentWidget()):
            return
        key = self._key()
        if self._tab_fits.get("key") != key:
            self._tab_fits = {"key": key}
        self._tab_fits[mw._fit_tab is mw.setup_page] = self._fit.applied()

    def _refit_layout(self):
        mw = self.mw
        size = mw._pages.size()
        mini = size.width() < MINI_SIZE.width() or size.height() < MINI_SIZE.height()
        if not mini:
            # measured with the whole window in place: while the mini player shows, the
            # hidden page's sizes go stale and it stayed the mini player at sizes the
            # whole window fits (nothing is painted before this returns)
            self._set_mini(False)
            mw.rail.compact(mw.rail._compact)
            mw._mixer_layout.setDirection(QBoxLayout.Direction.LeftToRight)
            mw._mixer_layout.setSpacing(14)
            for group in mw._decks[1:]:
                group[0].setMaximumHeight(16777215)
            responsive.touch(mw._pads_scroll)
            # room for a whole row of pads comes before the mixer, the status line and
            # the rest: without it they kept their room and the pads got a slit
            mw._pads_scroll.setMinimumHeight(mw.grid.row_height())
            narrow = mw.width() < 860   # two cards side by side get cramped below this
            # Translated controls can need more room than the fixed breakpoint.
            # Measure both Setup columns even while they are stacked, so growing
            # the window brings them back only when neither will be clipped. Only
            # while Setup shows (or before its first fit): measuring its cards took
            # ~1 ms of every resize step on the other tabs, and switching to it
            # fits it again (_fit_setup_tab).
            if mw._setup_stacked is None or mw.tabs.currentWidget() is mw.setup_page:
                body = mw.setup_page.widget()
                lay = body.layout() if body is not None else None
                holder = mw._setup_cols.parentWidget()
                assert lay is not None and holder is not None   # built in _build_setup_page
                margins = lay.contentsMargins()
                room = mw.setup_page.viewport().width() - margins.left() - margins.right()
                available = min(room, holder.maximumWidth())
                self._stack_cols[0](narrow or self._setup_need() > available)
            for apply in self._stack_cols[1:]:
                apply(narrow)
            need = self._fit.fit(size)   # even the smallest layout won't fit
            if need.width() > size.width() or need.height() > size.height():
                # A restored mixer needs one width pass before considering a wrap.
                need = self._fit.fit(size)
            if self._fit.live and (need.width() > size.width()
                                   or need.height() > size.height()):
                # dragging, measured with the sizes Qt cached: measured fresh before
                # giving up on the whole window (a stale size sent it into the mini
                # player at a size it fits)
                self._fit.live = False
                try:
                    need = self._fit.fit(size)
                finally:
                    self._fit.live = True
            if (mw.width() >= 760 and need.width() > size.width()
                    and mw.mixer.minimumSizeHint().width() + mw.rail.width() > size.width()):
                # Wrap only when the visible groups need it, e.g. with larger fonts.
                mw._mixer_layout.setDirection(QBoxLayout.Direction.TopToBottom)
                mw._mixer_layout.setSpacing(4)
                for group in mw._decks[1:]:
                    group[0].setMaximumHeight(0)
                mw.mixer.setMinimumSize(0, 0)
                mw._mixer_layout.activate()
                responsive.touch(mw.mixer)
                need = self._fit.fit(size)
            mini = need.width() > size.width() or need.height() > size.height()
            if mini and not self.is_mini():
                log.info("mini player at %dx%d: the window needs %dx%d (tab %s)",
                         size.width(), size.height(), need.width(), need.height(),
                         type(mw.tabs.currentWidget()).__name__)
        opening = getattr(mw.setctl, "_opening_settings", False)
        impctl = getattr(mw, "impctl", None)
        if mini and impctl is not None and impctl.packs_open() and not opening:
            impctl.close_packs()   # made too small for Free packs: as Settings
            self._refit_layout()
            return
        if mini and mw.setctl.settings_open() and not opening:
            # made too small for Settings: they close (as Done does), the mini player shows
            mw.setctl.close_settings()
            # close_settings requests a refit, which the outer transaction guards.
            # Finish it here with Settings removed, before painting resumes.
            self._refit_layout()
            return
        self._set_mini(mini)
        if mini:   # the pads too: cards with room for a couple of rows of them, else
            # one-line rows, so they can still be seen and played however small it gets
            room = self._mini_pad_room(size)
            mw.grid.set_slim(room < MINI_PAD_ROWS * self._mini_row(size))
            m = mw.grid.grid.contentsMargins()
            show = room >= SLIM_PAD_H + m.top() + m.bottom()
            if mw._pads_scroll.isHidden() == show:
                mw._pads_scroll.setVisible(show)
                toastmod.relayout(mw)   # icons on the pads, or none without them

    def _mini_pad_room(self, size: QSize) -> int:
        """The height above the mini player's card."""
        mw = self.mw
        m = mw._mini_v.contentsMargins()
        return (size.height() - m.top() - m.bottom() - mw._mini_v.spacing()
                - mw._mini_card.sizeHint().height())

    def _mini_row(self, size: QSize) -> int:
        """How tall a row of pads is in the mini player at this size."""
        mw = self.mw
        m, g = mw._mini_v.contentsMargins(), mw.grid.grid.contentsMargins()
        bar = mw._pads_scroll.verticalScrollBar().sizeHint().width()
        room = size.width() - m.left() - m.right() - g.left() - g.right() - bar
        return pad_height(mw.grid.fit_width(room, slim=False)[1]) + 10

    def grow_to_board(self):
        """The mini player's Full board button: the window grows, on its screen, to the
        board's size (Bun's "Open the full board" size, or what the board needs)."""
        mw = self.mw
        if mw.isMaximized() or mw.isFullScreen():
            mw.showNormal()
        from soundboard.ui.window.buncontrol import FULL_FROM_BUN
        room = mw.screen().availableGeometry() if mw.screen() else None
        g = mw.frameGeometry()
        want = FULL_FROM_BUN.expandedTo(self._fit.fit(mw._pages.size())
                                        if hasattr(self, "_fit") else MINI_SIZE)
        if room is not None:
            want = want.boundedTo(QSize(room.width() - 40, room.height() - 40))
        mw.resize(want.expandedTo(mw.size()))
        if room is not None:   # kept on the screen it grew on
            x = min(max(g.x(), room.left()), room.right() - mw.frameGeometry().width())
            y = min(max(g.y(), room.top()), room.bottom() - mw.frameGeometry().height())
            mw.move(max(x, room.left()), max(y, room.top()))
        self._refit()

    def is_mini(self) -> bool:
        mw = self.mw
        return mw._pages.currentIndex() == 1

    def _set_mini(self, on: bool):
        """Swap the whole window for the mini player (or back). The pads move with it."""
        mw = self.mw
        if on == self.is_mini():
            return
        achievements.live("mini", on)   # (Pocket Size)
        scroll = mw._pads_scroll
        with responsive.hold_updates(mw):
            mw.grid.set_two_up(on)
            if not on:
                mw.grid.set_slim(False)
            if on:
                scroll.setMinimumHeight(0)
                mw._mini_v.insertWidget(0, scroll, 1)
            else:
                home, index = mw._pads_home
                home.insertWidget(index, scroll, 1)
                scroll.setVisible(mw.ytresults.isHidden())   # results take the pads' place
            mw._pages.setCurrentIndex(1 if on else 0)
            mw.searchctl.apply_filter(mw.search.text())
        toastmod.relayout(mw)   # cards in the window, icons in the mini player

    def _squeeze_rail(self, tight: bool):
        """A narrow window: the rail shut (opened out, it shuts again) and the gap
        beside it narrower, so the pages keep their room before the mini player."""
        mw = self.mw
        mw.rail.squeeze(tight)
        side = (BODY_SIDE_TIGHT if tight else BODY_SIDE, BODY_SIDE)
        if mw.isRightToLeft():   # mirrored (Arabic): the rail is on the right
            side = side[::-1]
        mw._body_lay.setContentsMargins(side[0], self._body_top(), side[1], 10)
        if getattr(mw, "_mixer_tight", False):   # its room changed: measure it again
            self._fit_mixer(True)

    def setup_switching(self) -> bool:
        """Half-way into or out of Setup: the tab shows, _fit_setup_tab hasn't fitted
        the window for it yet (it does next, so a fit before it is wasted)."""
        mw = self.mw
        now, fitted = mw.tabs.currentWidget(), getattr(mw, "_fit_tab", None)
        return (hasattr(self, "_fit") and now is not fitted
                and mw.setup_page in (now, fitted))

    def _fit_setup_tab(self, _i: int):
        """Into or out of Setup: its width counts only while it shows (WidthScroll),
        so what gives way is worked out again, from scratch: every step undone and
        done again, the whole window measured 40-60 times (120 ms a switch on a slower
        PC). So what gave way on each side is kept, for this window size, and going
        back and forth puts it back as it was (measured once, to check)."""
        mw = self.mw
        was, mw._fit_tab = mw._fit_tab, mw.tabs.currentWidget()
        if not hasattr(self, "_fit") or mw.setup_page not in (was, mw._fit_tab):
            return
        fit = self._fit
        known = (self._tab_fits.get(mw._fit_tab is mw.setup_page)
                 if self._tab_fits.get("key") == self._key() else None)
        if known is None:
            fit.reset()
        else:
            fit.restore(known)
        self._refit()   # (and kept for this side: _note_side)

    def _rail_opened(self, on: bool):
        """The rail opened out or shut: save it, and fit the window to its new width
        (shut, what had given way for it comes back)."""
        mw = self.mw
        mw.set_option("sidebar_open", on)
        if hasattr(self, "_fit"):
            self._fit.reset()
            self._refit()

    def _body_top(self) -> int:
        """The body's top margin: none under Settings, whose heading rises level with
        the rail's name and keeps its pages where a tab's start (SettingsDialog)."""
        mw = self.mw
        return 0 if mw.setctl.settings_open() else 10

    def _fit_body_top(self):
        mw = self.mw
        m = mw._body_lay.contentsMargins()
        mw._body_lay.setContentsMargins(m.left(), self._body_top(), m.right(), m.bottom())

    def _fit_toolbar(self):
        """The toolbar spans the pads: in by the grid's margin on both sides, and by the
        scroll bar too while it shows (and the odd pixels a row can't split). The
        category tabs start on the same line as the toolbar and the first card."""
        mw = self.mw
        if getattr(mw, "grid", None) is None or getattr(mw, "_pad_scroll", None) is None:
            return   # the category bar is built before the pads; they fit it once they exist
        m = mw.grid.grid.contentsMargins()
        sb = mw._pad_scroll.verticalScrollBar()
        right = (m.right() + mw.grid.slack()
                 + (sb.sizeHint().width() if sb.maximum() > 0 else 0))
        hold = mw._toolbar_hold.layout()
        row = mw.catctl._cat_row.layout()
        if hold is None or row is None:
            return
        hold.setContentsMargins(m.left(), 0, right, 0)
        row.setContentsMargins(m.left(), 0, 0, 0)
        if sub := mw.catctl._sub_row.layout():
            sub.setContentsMargins(m.left(), 6, right, 0)

    def _fit_mixer(self, tight: bool):
        """The levels strip's responsive step. Only when the strip itself is too wide
        (not for whatever else is): one group whole, the other two as icons; still too
        wide, the % boxes go (the sliders still say it). "Others hear it" keeps its
        words: an empty box beside a mic icon said nothing, and it's the switch a warning
        sends you to."""
        mw = self.mw
        stages = (lambda: self._mixer_one_at_a_time(True),
                  lambda: (mw.vol_mic.spin.hide(), mw.vol_mon.spin.hide()))
        self._mixer_one_at_a_time(False)
        mw.vol_mic.spin.show()
        mw.vol_mon.spin.show()
        self._touch_mixer()
        mw._mixer_tight = tight
        if not tight:
            return
        side = mw._body_lay.contentsMargins()
        room = mw._pages.width() - mw.rail.minimumWidth() - side.left() - side.right()
        for stage in stages:
            if mw.mixer.minimumSizeHint().width() <= room:
                break
            stage()
            self._touch_mixer()

    def _touch_mixer(self):
        mw = self.mw
        responsive.touch(*mw._deck_tabs, mw.chk_mic, mw.vol_mic.spin,
                         mw.vol_mon.spin, mw.out_meter)

    def _mixer_one_at_a_time(self, on: bool):
        """Too narrow for the three groups: show one whole, the others as icons."""
        mw = self.mw
        mw._mixer_one = on
        for i, (deck, tab, title) in enumerate(zip(
                (g[-1] for g in mw._decks), mw._deck_tabs, mw._deck_titles)):
            whole = not on or i == mw._mixer_focus
            deck.setVisible(whole)
            tab.setVisible(not whole)
            title.setVisible(not on)   # the icon beside it (and its tooltip) says which
            # the shown group takes the room (what others hear, with all three)
            mw._mixer_layout.setStretchFactor(deck, int(i == (mw._mixer_focus if on else 1)))

    def _stack_setup(self, compact: bool):
        """Setup's cards in two columns, or in one column in setup order."""
        mw = self.mw
        if compact == mw._setup_stacked:
            return
        mw._setup_stacked = compact
        grid = mw._setup_cols
        for col in mw._setup_lr:
            while col.count():
                take_out(col)   # the cards stay on the page, only their places change
        paired = [w for pair in mw._setup_pairs for w in pair]
        for w in paired:
            grid.removeWidget(w)
        if not compact:
            for r, pair in enumerate(mw._setup_pairs):
                for c, w in enumerate(pair):
                    grid.addWidget(w, r, c)
        grid.setColumnStretch(1, 0 if compact else 1)   # (stacked: column 1 is empty)
        grid.setColumnStretch(0, 1)
        lcol, rcol = mw._setup_lr
        for w in mw._setup_narrow if compact else ():
            lcol.addWidget(w)
        if not compact:   # the rest under the pairs, in their own column
            for col, cards in zip(mw._setup_lr, mw._setup_wide):
                for w in cards:
                    if w not in paired:
                        col.addWidget(w)
        for col in mw._setup_lr:
            col.addStretch(1)

    def _place_pocket(self, have: bool):
        """Setup's cards with Onion Pocket's (`have`: it's installed) or without it.
        With it, it's on the left in Connect your chat's place, and Connect your chat
        goes to the right, under the EQ (the room there was empty); without it, the
        cards are where they always were."""
        mw = self.mw
        pocket = mw.pocket_card.frame
        how, dev, chat, dest, eq = mw._setup_cards
        if have:
            mw._setup_wide = ((how, dev, pocket), (dest, eq, chat))
            mw._setup_narrow = (how, dest, dev, chat, pocket, eq)
        else:
            mw._setup_wide = ((how, dev, chat), (dest, eq))
            mw._setup_narrow = (how, dest, dev, chat, eq)
        was = mw._setup_stacked
        mw._setup_stacked = None   # (so it's placed again)
        self._stack_setup(bool(was))
        pocket.setVisible(have)   # (after: in a layout, so never a window of its own)

    def _setup_one_col(self) -> int:
        """The width Setup needs in one column: its widest card, and the page's margins."""
        mw = self.mw
        widest = max(QWidgetItem(w).minimumSize().width() for w in mw._setup_narrow)
        inner = mw.setup_page.widget()
        lay = inner.layout() if inner is not None else None
        if lay is None:   # (built in _build_setup_page: always there)
            return widest
        m = lay.contentsMargins()
        return widest + m.left() + m.right()

    def _setup_need(self) -> int:
        """The width Setup's two columns need side by side, measured the same way
        whether they're stacked or not (stacked, the right column is empty)."""
        mw = self.mw
        return sum(max(QWidgetItem(w).minimumSize().width() for w in cards)
                   for cards in mw._setup_wide) + mw._setup_cols.spacing()
