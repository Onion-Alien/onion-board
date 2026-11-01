"""Making the main window's tabs (Radio, Voice, Apps, Triggers, Store) or their stand-ins when
switched off, and what they call back: the Store's links and samples, sharing a voice,
the Onion Watch add-on."""
from __future__ import annotations

import logging
from typing import Literal, overload

from PySide6.QtCore import QTimer

from soundboard.ui.kit import theme
from soundboard.core import achievements
from soundboard.online import net
from soundboard.core import usage
from soundboard.ui.kit import busy, icons
from soundboard.ui.window import taboff
from soundboard.ui.sounds.linkbar import PLAY_ID as LINK_ID
from soundboard.ui.apps.appspanel import AppsTab
from soundboard.ui.triggers.triggershost import BoardHost
from soundboard.ui.triggers.triggerstab import TriggersTab
from soundboard.ui.radio.radiopanel import RadioOff, RadioTab
from soundboard.ui.store.storetab import PREVIEW as STORE_PREVIEW, StoreTab
from soundboard.ui.voice.voicepanel import VoicePanel
from soundboard.ui.kit.widgets import Meter
from soundboard.i18n import _

from soundboard.ui.window.windowparts import WindowParts
log = logging.getLogger("soundboard.ui.window.mainwindow")


class WindowTabs(WindowParts):
    """MainWindow's tabs and their hooks (a mixin)."""

    def _make_radio(self):
        """The Radio tab, or with Radio switched off in Settings > Privacy & security a
        panel saying so: then no directory, player or web view is made at all. (The
        same panel stands in, hidden, while the tab is switched off in Settings > Tabs.)"""
        if net.allowed("radio") and self.tabctl.tab_on("radio"):
            r = RadioTab(self.engine, self.cfg, self._save_later, Meter)
            r.clip_ready.connect(self.soundctl.on_clip)
        else:
            r = RadioOff()
            r.open_settings.connect(lambda: self.setctl.open_settings("privacy"))
        r.active_changed.connect(self.tabctl._radio_live)
        self.radio_page.addWidget(r)
        self.radio_page.setCurrentWidget(r)
        return r

    @overload
    def _make_tab(self, key: Literal["voice"]) -> VoicePanel | taboff.VoiceOff: ...

    @overload
    def _make_tab(self, key: Literal["apps"]) -> AppsTab | taboff.TabOff: ...

    @overload
    def _make_tab(self, key: Literal["triggers"]) -> TriggersTab | taboff.TabOff: ...

    @overload
    def _make_tab(self, key: Literal["store"]) -> StoreTab | taboff.TabOff: ...

    @overload
    def _make_tab(self, key: str) -> (VoicePanel | AppsTab | TriggersTab | StoreTab
                                      | taboff.TabOff): ...

    def _make_tab(self, key: str):
        """The Apps, Triggers, Voice, Store or Chat tab, wired to the window; or, switched off in
        Settings > Tabs, its stand-in (nothing of the tab is made or loaded)."""
        if not self.tabctl.tab_on(key):
            self.tab_info.pop(key, None)
            if key != "voice":
                return taboff.TabOff()
            # effects add-ons still load: a sound's effects (Edit sound) use them too
            from soundboard.addons import modules
            modules.load_effects(modules.discover())
            return taboff.VoiceOff()
        if key == "voice":
            v = VoicePanel(self.engine, self.cfg.voice_fx, self.cfg.speech)
            v.fx_changed.connect(self._voice_fx_changed)
            v.speech_changed.connect(lambda s: self.set_option("speech", s))
            v.clip_ready.connect(self.soundctl.on_clip)
            v.fx.hotkey_asked.connect(self.hkctl.set_voice_hotkey)
            v.share_asked.connect(self.share_voice)
            from soundboard.ui.apps.clipshelf import ClipShelf
            recs = ClipShelf(self.engine, self.cfg, v, voice=True)
            recs.add_to_sounds.connect(self.soundctl.on_clip)
            recs.size_changed.connect(self._save_later)
            v.add_recordings(recs)
            v.bar.record_button.clicked.connect(
                lambda: self.soundctl.record_dialog(quick=True))
            v.fx.hotkey_cleared.connect(lambda n: self.hkctl.set_voice_hotkey(n, ""))
            v.ai.hotkey_asked.connect(self.hkctl.set_ai_voice_hotkey)
            v.ai.hotkey_cleared.connect(lambda i: self.hkctl.set_ai_voice_hotkey(i, ""))
            v.ai.keys = {n[3:]: c for n, c in self.cfg.voice_hotkeys.items()
                         if n.startswith("ai:") and c}   # (hotkeycontrol.AI_KEY)
            v.ai.voices_changed.connect(lambda: any(
                n.startswith("ai:") for n in self.cfg.voice_hotkeys)
                and self.hkctl.register_hotkeys())
            v.set_light(self.light_voice_on())
            v.light_changed.connect(self.set_light_voice)
            v.fx.renamed.connect(self.hkctl.voice_renamed)
            v.fx.keys = dict(self.cfg.voice_hotkeys)
            v.board_sounds = lambda: self.cfg.sounds   # the Background's "from my board"
            v.board_changed()
            v.set_view(self.cfg.voice_view)   # both cards: Voice changer and AI voices
            v.fx.view_toggle.changed.connect(lambda view: self.set_option("voice_view", view))
            v.room_changed.connect(   # (before the window fits the first time: nothing to do)
                lambda: hasattr(getattr(self, "fitctl", None), "_fit") and self.fitctl._refit())
        elif key == "apps":
            v = AppsTab(self.engine, self.cfg, self._save_later, Meter)
            v.clip_ready.connect(self.soundctl.on_clip)
            self.tab_info["apps"] = v.info
        elif key == "store":
            v = StoreTab(self.cfg, lambda path: self.impctl.import_files([path]),
                         self._store_sample, lambda: self.setctl.open_settings("privacy"),
                         self._save_later, self._store_link, self._voice_hooks(),
                         self._store_link_state, self.linkbar.play_audio)
            return v
        else:
            # the Onion Watch add-on, or Hoot and its download button until it's
            # installed; loaded by load_triggers
            v = TriggersTab(BoardHost(self), defer=True)
        v.active_changed.connect(lambda on, k=key: self.tabctl._tab_live(k, on))
        return v

    def _voice_hooks(self):
        """What the Store's Voices use of the Voice tab (its lists of your voices)."""
        from soundboard.ui.store.storevoices import VoiceHooks
        return VoiceHooks(lambda: (self.voice if isinstance(getattr(self, "voice", None),
                                                            VoicePanel) else None))

    def share_voice(self, pick: str = ""):
        """The Voice tab's "Share to the store…": the Share a voice window on that voice."""
        import html

        from soundboard.online import net, store
        from soundboard.ui.store.storevoices import open_share
        if not net.allowed(store.FEATURE):
            busy.toast(self, html.escape(net.off_message(store.FEATURE)), "error")
            return
        new = not getattr(self.cfg, "store_id", "")
        install = store.install_id(self.cfg)
        if new:
            self._save_later()
        open_share(self, install, self._voice_hooks(), pick)

    def _store_link(self, url: str, name: str, kind: str):
        """A shared link in the Store tab: played now ("now"), played after what's
        playing ("play") or added, downloaded from its site the way a pasted link is (the
        download bar shows how far it is). "pause" (or resume) and "stop" are for it
        while the player has it."""
        if kind in ("pause", "stop"):
            if self._store_link_state(url) in ("playing", "paused"):
                if kind == "stop":
                    self.playctl._stop_sound(LINK_ID)
                else:
                    st = self.engine.state(LINK_ID)
                    self.engine.set_paused(LINK_ID, not (st and st[1]))
                self.tickctl._wake()
            return
        self.linkbar.open(url, name)
        if kind == "now":
            self.linkbar.play_now(solo=True)   # as a pad's press: the sounds playing stop
        elif kind == "play":
            self.linkbar.play_once()
        else:
            self.linkbar.add()

    def _store_link_state(self, url: str) -> str:
        """A Store card's link in the player: "playing", "paused", "loading" (its Play's
        download runs) or ""."""
        lb = self.linkbar
        if lb.playing_url == url and (st := self.engine.state(LINK_ID)) is not None:
            return "paused" if st[1] else "playing"
        return "loading" if lb._busy == "play" and lb._busy_url == url else ""

    def _store_sample(self, data, gain: float) -> bool:
        """The Store tab's "hear it first": to your headphones only (None stops it).
        False: no headphones to play it on."""
        if data is None:
            self.engine.stop(STORE_PREVIEW)
            return True
        return self.engine.play(STORE_PREVIEW, data, gain, mode="restart",
                                preview=True) is not None

    def load_triggers(self):
        """Put the Onion Watch add-on into the Triggers tab (~0.4 s on the UI thread).
        At the start it's done while the window is built, behind the loading screen (it
        draws on its own thread), so opening the tab is instant; also when the tab is
        switched back on in Settings > Tabs. Runs once."""
        if not isinstance(self.triggers, TriggersTab) or not self.triggers.pending \
                or self._shut_down:   # (switched off: its stand-in has nothing pending)
            return
        self.triggers.load()
        if self.triggers.needs_nudge():
            self._nudge_triggers(self.tabs.indexOf(self.triggers))

    def _nudge_triggers(self, index: int):
        """Triggers were being watched before they moved into the Onion Watch add-on,
        which isn't installed: tint the tab and say so once, until the tab is opened."""
        icons.set_tab_icon(self.tabs, index, "triggers", "warn_text")
        QTimer.singleShot(0, self, lambda: self.say(
            _("<span style='color:{status}'>Your screen triggers now come from the free Onion "
              "Watch add-on: open the Triggers tab to get it.</span>",
              status=theme.status('warn')), "warn", 10000,
            action=(_("Open Triggers"), lambda: self.tabs.setCurrentWidget(self.triggers))))

        def seen(i: int):
            if self.tabs.widget(i) is self.triggers:
                self.tabs.currentChanged.disconnect(seen)
                self._nudge_seen = None
                self.triggers.nudged()
                icons.set_tab_icon(self.tabs, index, "triggers")
        if getattr(self, "_nudge_seen", None) is not None:   # the tab made again (Settings
            self.tabs.currentChanged.disconnect(self._nudge_seen)   # > Tabs): one hook
            self._nudge_seen = None
        if self.tabs.currentWidget() is self.triggers:
            self.triggers.nudged()
            icons.set_tab_icon(self.tabs, index, "triggers")
        else:
            self._nudge_seen = seen
            self.tabs.currentChanged.connect(seen)

    def _voice_fx_changed(self, spec: dict):
        if spec.get("enabled"):
            usage.used("voice-changer")
            achievements.add("voices", str(spec.get("preset") or ""))
            achievements.voice_picked(str(spec.get("preset") or ""))
        self.set_option("voice_fx", spec)
        # off, a voice changer decides whether your mic still goes out: the switch says so
        # (tied to the button: a window closing meanwhile drops it)
        QTimer.singleShot(0, self.btn_air, lambda: self.set_sending(self.btn_air.isChecked()))
