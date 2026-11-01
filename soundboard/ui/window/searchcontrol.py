"""The Sounds tab's search box: filtering the pads as you type, a link pasted in it (played,
downloaded or retried), searching YouTube and other sites from it, and putting the
categories back when the web results close.

MainWindow makes one ``SearchControl`` (``MainWindow.searchctl``); everything here runs on
the UI thread."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt

from soundboard.core import achievements
from soundboard.sounds import library, sourceinfo
from soundboard.online import net, ytdl
from soundboard.audio.engine import SR
from soundboard.i18n import _, ngettext
from soundboard.sounds.library import SoundMeta
from soundboard.ui.kit import busy, icons
from soundboard.ui.window.controller import Controller
from soundboard.ui.sounds.linkbar import PLAY_ID as LINK_ID

if TYPE_CHECKING:
    from soundboard.ui.window.mainwindow import MainWindow


class SearchControl(Controller):
    """The search box of one MainWindow (``mw``)."""

    def __init__(self, mw: MainWindow):
        super().__init__(mw)
        self._link_meta: SoundMeta | None = None   # the link bar's Play once
        self._link_url = ""                        # ...and the page it came from

    def on_link_played(self, title: str, data, gain: float, url: str = ""):
        """The link bar's Play once: show it in the transport bar like a pad, so it
        can be paused, stopped and seeked. It isn't a sound in the library."""
        mw = self.mw
        self._link_meta = SoundMeta(id=LINK_ID, name=title, file="", level_gain=gain,
                                    duration=len(data) / SR)
        self._link_url = url or mw.linkbar.url   # its own page (another card may show)
        mw.audio[LINK_ID] = data
        if mw.current == LINK_ID:
            mw.current = None   # a new link: refresh the name
        mw.playctl.select(LINK_ID)

    def _on_site_picked(self, key: str):
        """A site picked in the search button's menu: it shows that site, and the
        search box's words are searched there now (open results re-run themselves)."""
        mw = self.mw
        icons.set_icon(mw.btn_yt, key, "accent", "accent", size=18)
        self._drop_link()   # the last site's song, if it's over: its card goes too
        if mw.ytresults.isHidden() and mw.search.text().strip():
            self.search_youtube()

    def search_youtube(self):
        """Enter / the Search button: search the site the results header has
        picked (ytdl.SOURCES) for the search box's text (a pasted link is the
        link bar's instead)."""
        mw = self.mw
        self.flush_search()
        text = mw.search.text()
        if ytdl.as_link(text) or ytdl.as_links(text):
            self._show_link()
            return
        if not mw.ytresults.available():
            return
        if not mw.ytresults.search(text):
            if not text.strip():
                mw.search.setFocus()
                busy.flash(mw.btn_yt, _("Type something first"))
            return
        self._results_shown()

    def _results_shown(self):
        """Web results take the pads' place."""
        mw = self.mw
        mw._pads_scroll.hide()
        mw.catctl._cat_row.hide()
        mw.fitctl._results_open = True
        mw.fitctl._sync_cat_bar()

    def on_search_enter(self):
        mw = self.mw
        self.flush_search()   # a link pasted a moment ago: the link bar has it now
        text = mw.search.text()
        if ytdl.as_link(text) or ytdl.as_links(text):
            self._show_link()   # its card, at once: nothing downloads until Play / Add
        else:
            self.search_youtube()

    def _on_link_changed(self, url: str):
        """The search box's link changed: show its card once it stays (a link typed by
        hand is a new one at every key); no link any more: its card goes."""
        mw = self.mw
        if url:
            mw._link_wait.start()
            return
        mw._link_wait.stop()
        if mw.ytresults.link and not mw.ytresults.isHidden():
            mw.ytresults.close_results()

    def _on_links_changed(self, urls: list):
        """Several links pasted: their cards once the box stays like that; none any
        more: their cards go."""
        mw = self.mw
        if urls:
            mw._link_wait.start()
            return
        mw._link_wait.stop()
        if mw.ytresults.links and not mw.ytresults.isHidden():
            mw.ytresults.close_results()

    def _show_links(self):
        """Several links pasted: a card each, looked up, not downloaded (Add all)."""
        mw = self.mw
        urls = [u for u in mw.linkbar.many if ytdl.site_allowed(u)]
        if not urls:
            mw.toast(net.off_message(ytdl.site_feature(mw.linkbar.many[0])))
            return
        if mw.ytresults.show_links(urls):
            self._results_shown()

    def add_all(self, results: list):
        """Add all on the pasted links' cards: each one not on the board yet goes to the
        download queue (one downloads, the rest wait their turn in the download bar)."""
        mw = self.mw
        new = [r for r in results if self._pad_for_link(r.url) is None]
        have = len(results) - len(new)
        achievements.links_added(len(new))   # (Bulk Buyer)
        for r in new:
            self._from_youtube(r, play=False)
        if have:
            mw.toast(ngettext("{n} of them is on your board already.",
                              "{n} of them are on your board already.", have))

    def _show_link(self):
        """The search box's link as a result card: looked up, not downloaded."""
        mw = self.mw
        mw._link_wait.stop()
        url = mw.linkbar.url
        if not url and mw.linkbar.many and not mw.fitctl.is_mini():
            self._show_links()
            return
        if not url or mw.fitctl.is_mini():
            return
        if not ytdl.site_allowed(url):
            # Offline mode or that site switched off: say so once per link, not nothing
            if url != getattr(self, "_link_off_said", None):
                self._link_off_said = url
                mw.toast(net.off_message(ytdl.site_feature(url)))
            return
        if not mw.ytresults.show_link(url):
            return
        self._results_shown()

    def _retry_download(self, item: dict):
        """The download bar's Retry on a pick that failed: picked again, as if its
        search card was clicked (it starts, or waits its turn)."""
        mw = self.mw
        kind = item["kind"]
        mw.linkbar.open(item["url"], item["title"], item["seconds"])
        mw.ytresults.mark(item["url"], kind)
        if not (mw.linkbar.play_once() if kind == "play" else mw.linkbar.add()):
            mw.ytresults.mark(item["url"], kind, False)

    def _from_youtube(self, r, play: bool):
        mw = self.mw
        if play and r.url == self._link_url and mw.audio.get(LINK_ID) is not None:
            mw.playctl.select(LINK_ID)   # already in the player: Play / Space pause and resume it
            mw.playctl.toggle_play_pause()
            return
        pad = self._pad_for_link(r.url) if play else None
        if pad is not None:   # it's on the board already: the pad plays, from the start
            mw.playctl.play(pad)
            return
        kind = "play" if play else "add"
        mw.linkbar.open(r.url, r.title, r.seconds)
        mw.ytresults.mark(r.url, kind)   # its button greys out until the link bar's done
        if not (mw.linkbar.play_once() if play else mw.linkbar.add()):
            mw.ytresults.mark(r.url, kind, False)

    def _pad_for_link(self, url: str) -> str | None:
        """The board's sound downloaded from this link (its audio loaded), or None."""
        mw = self.mw
        key = sourceinfo.link_key(url)
        if not key:
            return None
        for m in mw.cfg.sounds:
            if (mw.audio.get(m.id) is not None and isinstance(m.source, dict)
                    and sourceinfo.link_key(m.source.get("link", "")) == key):
                return m.id
        return None

    def _drop_link(self):
        """Take a stopped web song out of the player. It stayed there as the player's
        sound, and once its card was gone (another site searched) nothing took it out:
        ■ only stopped it and its name sat in the bar for good."""
        mw = self.mw
        if LINK_ID in mw.engine.playing():
            return   # still playing or paused: the player keeps it
        self._link_meta, self._link_url = None, ""
        mw.audio.pop(LINK_ID, None)
        if mw.current == LINK_ID:
            mw.playctl.deselect()

    def _results_closed(self):
        """"My sounds": all of them. The search box also filters the pads, so the web
        search still in it left a board of only the pads matching "cat meow" (often
        none, with nothing saying why). Something else typed in it since stays."""
        mw = self.mw
        mw.fitctl._results_open = False
        mw.fitctl._sync_cat_bar()
        query = " ".join(mw.ytresults.query.split())
        if query and " ".join(mw.search.text().split()) == query:
            mw.search.clear()

    def _on_search_edited(self, text: str):
        # typed: Qt sends this just before textChanged (the box's clear button sends
        # it just after; that change has filtered at once, and the next one is unequal)
        mw = self.mw
        mw._search_typed = text

    def _on_search_text(self, text: str):
        mw = self.mw
        if "\n" in text or "\r" in text:   # links pasted a line each: one line of them
            flat = " ".join(text.split())
            mw._search_typed = flat if mw._search_typed == text else None
            mw.search.setText(flat)   # (this again, with the flat text)
            return
        typed, mw._search_typed = mw._search_typed == text, None
        if typed:
            mw._search_wait.start()   # each key restarts it: filter once typing pauses
        else:
            self.apply_filter(text, lazy=True)

    def flush_search(self):
        """Filter the pads for the search box now, if typing left that waiting."""
        mw = self.mw
        if mw._search_wait.isActive():
            self.apply_filter(mw.search.text(), lazy=True)

    def apply_filter(self, text, lazy: bool = False):
        """Show the pads that match the search box (name or category) and are in the
        category picked above the pads. `lazy`: skip the regrid when no pad changed."""
        mw = self.mw
        mw._search_wait.stop()   # this is the filter typing was waiting for
        mw.linkbar.set_text(text)
        if getattr(mw, "overlay", None) is not None:   # every sounds / category edit ends here
            mw.overlay.sounds_changed()
        # a link filters nothing, and nor does the box in the mini player, which hides
        # it: a web search's words left there showed a blank mini player
        t = ("" if mw.linkbar.url or mw.linkbar.many or mw.fitctl.is_mini()
             else text.strip().lower())
        cat, sub, hidden = mw.cfg.category, mw.cfg.subcategory, mw.cfg.hidden_from_all
        changed = False
        for m in mw.cfg.sounds:
            p = mw.pads.get(m.id)
            if p:
                hit = not t or t in m.name.lower() or any(t in g.lower() for g in m.tags)
                hide = not hit or not library.in_view(m.tags, cat, sub, hidden)
                changed = changed or bool(p.property("filtered")) != hide
                p.setProperty("filtered", hide)
        if changed or not lazy:
            mw.grid.relayout(force=True)
            mw.selection.sync()

    def focus_search(self):
        """Ctrl+F: the cursor into Search sounds, with what's there selected."""
        mw = self.mw
        mw.search.setFocus(Qt.FocusReason.ShortcutFocusReason)
        mw.search.selectAll()
