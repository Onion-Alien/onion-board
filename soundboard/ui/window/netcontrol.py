"""The main window following the network and privacy switches: Offline mode, a feature
switched off (search, the cable download, Radio), the proxy and Tor lines on the output
card, the remote-control line, and saying how far Tor is when something waits for it.

MainWindow makes one ``NetControl`` (``MainWindow.netctl``); everything here runs on the
UI thread."""
from __future__ import annotations

import html
from dataclasses import replace
from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QMenu

from soundboard.online import net, tor
from soundboard.control import remote
from soundboard.i18n import _
from soundboard.ui.kit import busy
from soundboard.ui.settings import lite
from soundboard.ui.window import onaircard
from soundboard.ui.window.controller import Controller
from soundboard.ui.radio.radiopanel import RadioTab
from soundboard.ui.window.tabcontrol import TAB_INDEX
from soundboard.ui.kit.widgets import fit_placeholder

if TYPE_CHECKING:
    from soundboard.ui.window.mainwindow import MainWindow


VOICE_TAB = "voice:"   # a card line's page that's a Voice tab ("voice:clean"), not Settings
# the Voice tabs a click on their card line switches off and on, and the voices that are
# (VoiceSwitch's keys; Clean mic isn't a voice): Languages is the computer voice and the
# translating both. Add-ons isn't one: its line opens its tab
VOICE_SWITCHES = {"clean": (), "fx": ("fx",), "ai": ("ai",), "speak": ("speak", "lang")}


class NetControl(Controller):
    """The network and privacy follow-ups of one MainWindow (``mw``)."""

    def __init__(self, mw: MainWindow):
        super().__init__(mw)
        self._tor_told = ""             # what the last Tor toast said (one per change)
        self._clean_off = False         # Clean mic switched off from its card line

    def _follow_switches(self):
        """Settings > Privacy & security changed: the parts of the window that go
        online follow their switches."""
        mw = self.mw
        self._radio_follow_switch()
        mw.statusctl._update_flow()   # the cable's install button (_cable_follow_switch)
        self._search_follow_switch()
        self._offline_follow()
        if hasattr(mw.fitctl, "_fit"):   # buttons came or went: what fits is measured again
            mw.fitctl._refit()

    def _offline_follow(self):
        """Offline mode: Offline in the On Air card, and the tabs that only work online
        (needs_online) out of the tab bar and + More tabs; back when it's off."""
        mw = self.mw
        self._net_follow()
        for key in ("radio", "triggers"):
            i = TAB_INDEX[key]
            shown = mw.tabctl.tab_shown(key)
            if not shown and mw.tabs.currentIndex() == i:
                mw.tabs.move_to(0)   # (Settings, where this is done, stays up)
            mw.tabs.setTabVisible(i, shown)
        mw.tabctl._update_more_tabs()

    def _search_follow_switch(self):
        """Finding sounds online switched off: no Search button, and the search box
        only filters your own sounds (and says so)."""
        mw = self.mw
        online = mw.ytresults.available()
        mw.btn_yt.setVisible(online)
        if online:
            fit_placeholder(mw.search, _("Search sounds or paste a link"),
                            _("Search sounds"), _("Search"))
        else:
            fit_placeholder(mw.search, _("Search your sounds"), _("Search"))
        mw.search.setAccessibleName(_("Search sounds or paste a link") if online
                                    else _("Search your sounds"))
        mw.search.setToolTip(mw._search_tip if online else _("Type to filter your sounds"))
        if hasattr(mw, "fitctl"):
            mw.fitctl.search_button_changed()

    def _cable_follow_switch(self):
        """The cable's install button downloads it (from vb-audio.com): gone in Offline
        mode, greyed with its switch off. On the mic route the same button sets up the
        mic, which goes nowhere online."""
        mw = self.mw
        if busy.is_busy(mw.btn_install):
            return
        cable = mw.cfg.route != "mic"
        allowed = not cable or net.allowed("setup_downloads")
        if cable and net.offline():
            mw.btn_install.hide()
        mw.btn_install.setEnabled(allowed)
        mw.btn_install.setToolTip("" if allowed else net.off_message("setup_downloads"))

    def _radio_follow_switch(self):
        """Radio switched off: the tab becomes the "off" panel (a playing station
        stops); switched back on, the tab is built again."""
        mw = self.mw
        on = net.allowed("radio") and mw.tabctl.tab_on("radio")
        if on == isinstance(mw.radio, RadioTab):
            return
        old, playing = mw.radio, mw.radio.is_active()
        old.shutdown()
        if hasattr(mw.fitctl, "_fit"):   # undone while the old tab's widgets still exist
            mw.fitctl._fit.remove(mw._radio_steps)
        mw.radio = mw._make_radio()
        mw.radio_page.removeWidget(old)
        old.deleteLater()
        if hasattr(mw.fitctl, "_fit"):
            mw._radio_steps = mw.radio.fit_steps()
            mw.fitctl._fit.extend(mw._radio_steps)
            mw.fitctl._refit()
        mw.tabctl._radio_live(False)
        if playing:
            mw.toast(html.escape(_("Radio was switched off, so the station stopped.")))

    def card_lines(self) -> list[onaircard.Line]:
        """What the On Air card says under its status (OutputBlock.set_lines): how the
        app goes online, a remote control listening, lite mode, and the Voice tabs that
        are on."""
        connection = (replace(line, group="connection")
                      for line in (self._network_line(), self._remote_line()) if line)
        return [*self._voice_lines(), *connection,
                *(line for line in (self._lite_line(),) if line)]

    def _voice_lines(self) -> list[onaircard.Line]:
        """A line for each Voice tab that's on (Clean mic, the voice changer, an AI voice,
        another language): they change your mic on every tab, so the card says so
        wherever you are, in green. One switched off from here (or paused on the Voice
        tab) stays, in red, to switch back on with a click, until the app closes."""
        voice = getattr(self.mw, "voice", None)
        live = getattr(voice, "live_tabs", None)
        if voice is None or live is None:   # (the Voice tab switched off in Settings)
            return []
        from soundboard.ui.voice.voicecards import CARD_ICONS, TAB_KEYS, TAB_NAMES
        on = {key for key, _icon, _name in live()}
        if "clean" in on:   # on again, from anywhere: no longer waiting here
            self._clean_off = False
        paused = set(voice.paused_keys())
        lines = []
        for key in TAB_KEYS:
            name = TAB_NAMES[key]()
            if key in on:
                tip = (_("Click to turn it off. Right-click to open it.")
                       if key in VOICE_SWITCHES else _("Click to change it."))
                tone = "ok"
            elif (self._clean_off if key == "clean"
                  else paused & set(VOICE_SWITCHES.get(key, ()))):
                tip, tone = _("Off. Click to turn it back on. Right-click to open it."), "error"
            else:
                continue
            lines.append(onaircard.Line(CARD_ICONS[key], name, tone, "\n".join((name, tip)),
                                        VOICE_TAB + key, "voice"))
        return lines

    def toggle_voice(self, key: str):
        """A Voice tab's line clicked: on, it goes off (it stays, in red); off, it comes
        back as it was. The Voice tab's own pause does the same (VoiceSwitch.toggle_one)."""
        voice = self.mw.voice
        if key == "clean":
            was = voice.clean.is_on()
            voice.clean.set_on(not was)
            self._clean_off = was and not voice.clean.is_on()
        else:
            keys = VOICE_SWITCHES[key]
            on = [k for k in keys if k in voice.on_keys()]
            for k in on or [k for k in keys if k in voice.paused_keys()]:
                voice.toggle_one(k)
        self._net_follow()

    def remove_voice(self, key: str):
        """A Voice tab's line's Remove: off, and its line goes (as the Voice tab's close
        button: the Voices switch won't bring it back either)."""
        voice = self.mw.voice
        if key == "clean":
            voice.clean.set_on(False)
            self._clean_off = False
        else:
            for k in VOICE_SWITCHES[key]:
                voice.forget_one(k)
        self._net_follow()

    def line_menu(self, page: str, pos: QPoint):
        """A Voice tab's line right-clicked: its menu (voice_menu), where it was clicked."""
        menu = self.voice_menu(page)
        if menu is not None:
            menu.exec(pos)

    def voice_menu(self, page: str) -> QMenu | None:
        """A Voice tab's line's menu: Open it there, or Remove it from the card (None for
        the other lines)."""
        key = page[len(VOICE_TAB):] if page.startswith(VOICE_TAB) else ""
        if key not in VOICE_SWITCHES:
            return None
        menu = QMenu(self.mw)
        menu.addAction(_("Open"), lambda: self.open_page(page))
        menu.addAction(_("Remove"), lambda: self.remove_voice(key))
        return menu

    @staticmethod
    def _lite_line() -> onaircard.Line | None:
        """Lite mode on (Settings > General), else None."""
        if not lite.on():
            return None
        return onaircard.Line("leaf", _("Lite mode"), "",
                            _("Lite mode is on: no animations, plain themes and less CPU. "
                              "Click to change it."), "general")

    def _network_line(self) -> onaircard.Line | None:
        """Offline mode, a proxy or Tor (and how far Tor got), or None when direct."""
        if net.offline():
            return onaircard.Line("offline", _("Offline"), "",
                                _("Offline mode is on: nothing goes online, and what needs "
                                  "the internet is hidden. Click to change it."), "privacy")
        mode = net.mode()
        click = _("Click to change it.")
        if mode == net.TOR:
            t = tor.manager()
            tip = "\n".join((t.status_text(), click))
            if t.state == tor.READY:
                return onaircard.Line("tor", _("Through Tor"), "ok", tip, "privacy")
            if t.state == tor.STARTING:
                return onaircard.Line("tor", _("Tor {percent}%", percent=t.progress), "", tip,
                                    "privacy")
            if t.state == tor.FAILED:
                return onaircard.Line("tor", _("Tor failed"), "warn", tip, "privacy")
            return onaircard.Line("tor", _("Tor"), "", tip, "privacy")
        if mode == net.PROXY:
            p = net.proxy()
            if p is None:
                return onaircard.Line("shield", _("Proxy not working"), "warn",
                                    "\n".join((net.describe(), click)), "privacy")
            return onaircard.Line("shield", _("Through proxy"), "ok",
                                "\n".join((_("Everything goes through your proxy "
                                             "({address}).", address=p.where), click)),
                                "privacy")
        return None

    def _remote_line(self) -> onaircard.Line | None:
        """A phone remote (a remote add-on such as Onion Pocket) listening on the home
        network, or else the control API listening on this PC; None when neither."""
        servers = remote.listening()
        click = _("Click to change it.")
        phone = [s for s in servers if s.lan]
        if phone:
            return onaircard.Line("phone", _("Phone remote on"), "ok",
                                "\n".join((_("Phones on your home network can control the "
                                             "board ({address}).",
                                             address=f"{phone[0].host}:{phone[0].port}"),
                                            click)), "remote")
        if servers:
            return onaircard.Line("phone", _("Remote control on"), "",
                                "\n".join((_("Stream Deck buttons and scripts on this PC "
                                             "can control the board (port {port}).",
                                             port=servers[0].port), click)), "remote")
        return None

    def _remote_watch(self):
        mw = self.mw
        mw.remote_changed.emit()   # (maybe from the thread that stopped it)

    def open_line(self, page: str):
        """A card line clicked: a Voice tab's line switches it off or back on (toggle_voice);
        the rest open their page."""
        key = page[len(VOICE_TAB):] if page.startswith(VOICE_TAB) else ""
        if key in VOICE_SWITCHES:
            self.toggle_voice(key)
        else:
            self.open_page(page)

    def open_page(self, page: str):
        """A card line's Settings page, or its tab on the Voice tab."""
        mw = self.mw
        if not page.startswith(VOICE_TAB):
            mw.setctl.open_settings(page)
            return
        if mw.tabctl.tab_on("voice"):
            mw.tabs.setCurrentWidget(mw.voice)
            mw.voice._open_card(page[len(VOICE_TAB):])

    def _net_follow(self):
        mw = self.mw
        output = getattr(getattr(mw, "rail", None), "output", None)
        if output is not None:
            output.set_lines(self.card_lines())
            mw.rail.refresh_output()   # (the card's widest line can change its scale)

    def _on_tor(self):
        """Something is waiting for Tor: say so (once), and when it's ready or failed."""
        mw = self.mw
        self._net_follow()
        t = tor.manager()
        if t.state == tor.STARTING and t.waiting:
            say = ("starting", _("Connecting to Tor… what you asked for goes once it's "
                                  "connected (Settings → Privacy & security shows how far "
                                  "it is)."), "")
        elif t.state == tor.READY and self._tor_told == "starting":
            say = ("ready", _("✓ Connected to Tor."), "ok")
        elif t.state == tor.FAILED and self._tor_told in ("starting", "") and t.waiting:
            say = ("failed", _("Couldn't connect to Tor: {error}. Nothing was sent "
                               "without it.", error=t.message), "error")
        elif t.state == tor.OFF:
            self._tor_told = ""
            return
        else:
            return
        if say[0] != self._tor_told:
            self._tor_told = say[0]
            mw.toast(html.escape(say[1]), say[2])
