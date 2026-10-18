"""The urgent bar in the main window and what feeds it: an important fix for Onion Board or
Onion Watch, Discord's own settings hurting your sounds (discordcfg), and apps recording
your mic around the mic effect (rawmic). One warning at a time, each can be hidden.

MainWindow makes one ``AlertControl`` (``MainWindow.alertctl``) and sends it the bridge's
``mic_users`` / ``discord`` signals. The looks run on workers; everything here runs on the
UI thread."""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from soundboard.audio import appaudio
from soundboard.mic import directmic, discordcfg, rawmic
from soundboard.core import updates
from soundboard.i18n import _
from soundboard.core.pollthread import PollThread
from soundboard.ui.kit import busy
from soundboard.ui.controller import Controller
from soundboard.ui.triggers.triggerstab import TriggersTab

if TYPE_CHECKING:
    from soundboard.ui.mainwindow import MainWindow

log = logging.getLogger(__name__)

# the urgent bar's line for the worst thing in Discord's settings (discordcfg)
DISCORD_URGENT = {
    discordcfg.STUDIO: _("{name} isn't hearing your sounds: its Input Profile is Studio, "
                         "which skips Onion Board. Set it to Custom."),
    discordcfg.BYPASS: _("{name} isn't hearing your sounds: \"Bypass System Audio Input "
                         "Processing\" is on, which skips Onion Board."),
    discordcfg.VAD: _("{name}'s Advanced Voice Activity cuts most of your sounds in calls. "
                      "Turn it off (Voice & Video → Show Advanced Voice Settings)."),
    discordcfg.AUTO: _("{name}'s automatic input sensitivity keeps cutting your sounds out "
                       "in calls. Turn it off (Voice & Video → Input Sensitivity)."),
    discordcfg.ISOLATION: _("{name}'s Voice Isolation is wiping out your sounds. Set its "
                            "Input Profile to Custom and Noise Suppression to None."),
    discordcfg.KRISP: _("{name}'s noise suppression (Krisp) is wiping out your sounds. Set "
                        "Noise Suppression to None."),
    discordcfg.SUPPRESSION: _("{name}'s noise suppression is eating your sounds. Set Noise "
                              "Suppression to None."),
    discordcfg.ECHO: _("{name}'s echo cancellation is making your sounds dip and pump. "
                       "Turn it off."),
    discordcfg.AGC: _("{name}'s automatic gain control is making your sounds' volume jump. "
                      "Turn it off."),
}


DISCORD_QUIT_S = 4.0   # the longest quitting waits for Discord's settings to be put back


def _talk_snapshots(found: list, seen: set) -> dict:
    """{Discord folder: discordtalk.snapshot} for each client seen for the first time
    while set for talking (any thread: reads its files)."""
    from soundboard.mic import discordtalk
    out = {}
    for d, name in discordcfg.CLIENTS:
        s = next((x for x in found if x.client == name), None)
        if s is None or d in seen or not discordtalk.talking(s):
            continue
        store = discordtalk.read_store(d)
        if store is not None:
            out[d] = discordtalk.snapshot(store)
    return out


class AlertControl(Controller):
    """The urgent bar and its checks for one MainWindow (``mw``)."""

    def __init__(self, mw: MainWindow):
        super().__init__(mw)
        self._urgent_hidden: set[str] = set()   # "board 1.9.6" / "watch 0.8.2", this run
        # Discord's own voice settings (discordcfg), read while it runs: the ones that
        # wipe out sounds get the urgent bar
        self.discord_found: list = []
        self._discord_sig = None
        self._discord_reading = False
        self._discord_poll = PollThread("discord-settings")
        self._talk_seen: set[str] = set()   # Discord folders looked at for how you talk
        # straight into my mic: an app recording the mic in raw mode skips Onion Board
        # and hears none of the sounds (rawmic)
        self.raw_watch = rawmic.BypassWatch()
        self._raw_looking = False
        self._raw_poll = PollThread("raw-mic")

    def _urgent_now(self) -> tuple[str, str, str] | None:
        """The urgent fix to show on the banner: (key, text, button), Onion Board's
        before Onion Watch's; None when there's none, or it was hidden."""
        mw = self.mw
        rel = mw.updctl.release
        if (rel is not None and rel.urgent
                and f"board {rel.version}" not in self._urgent_hidden):
            # the same steps as the update card (its progress shows under the words)
            button = (_("Cancel") if mw.updctl._downloading
                      else _("Restart to update") if mw.updctl._update_file is not None
                      and not mw.updctl._update_err
                      else _("Try again") if mw.updctl._update_err
                      else _("Update now") if updates.can_install() and rel.asset_url
                      else _("Details"))
            return (f"board {rel.version}",
                    _("Important fix in Onion Board {version}: {fix}",
                      version=rel.version, fix=rel.urgent), button)
        o = mw.watch_offer   # only on its Triggers tab: there it's the one in use
        if (o is not None and f"watch {o.version}" not in self._urgent_hidden
                and mw.tabs.currentWidget() is mw.triggers):
            return (f"watch {o.version}",
                    _("Important fix in Onion Watch {version}: {fix}",
                      version=o.version, fix=o.urgent),
                    _("Update Onion Watch"))
        probs = self.discord_problems()
        key = "discord " + ",".join(probs)
        if probs and key not in self._urgent_hidden:
            return key, DISCORD_URGENT[probs[0]].format(
                name=self.discord_found[0].client), _("Fix Discord")
        raw = self._raw_culprits()
        key = "rawmic " + ",".join(a.exe.lower() for a in raw)
        if raw and key not in self._urgent_hidden:
            if len(raw) == 1:
                text = _("{name} is using your mic without Onion Board, so it won't hear "
                         "your sounds. Look for a \"raw\", \"bypass processing\" or "
                         "\"studio\" option in its voice settings and turn it off.",
                         name=raw[0].name)
            else:
                text = _("One of these apps is using your mic without Onion Board, so it "
                         "won't hear your sounds: {names}. Look for a \"raw\", \"bypass "
                         "processing\" or \"studio\" option in its voice settings and turn "
                         "it off.", names=", ".join(a.name for a in raw))
            return key, text, ""
        return None

    def _raw_culprits(self) -> list:
        """The apps recording the mic in raw mode (rawmic), but not a Discord whose own
        settings already have their line (Studio, Bypass)."""
        raw = self.raw_watch.culprits
        if raw and self.discord_problems():
            from soundboard.ui.chatguide import DISCORD_EXES
            raw = [a for a in raw if a.exe.lower() not in DISCORD_EXES]
        return raw

    def _raw_tick(self):
        """Every RAW_POLL_MS while sending straight into the mic: who records it, on a
        worker (Windows' session list); compared with the effect's streams after."""
        mw = self.mw
        e = mw.engine
        mic = mw.cfg.mic_device
        if (mw.cfg.route != "mic" or e.direct_stream() is None or not mic
                or mw.micctl._direct_not_running()):
            shown = bool(self.raw_watch.culprits)
            self.raw_watch.reset()
            if shown:
                self._show_urgent()
            return
        if self._raw_looking:
            return
        self._raw_looking = True

        def run():
            try:
                # in the endpoint effect nobody can skip it, and one copy serves every
                # app (its stream count isn't per app): nobody to name
                return [] if directmic.endpoint_wide() else \
                    appaudio.recording_apps(mic, mine=True)
            except Exception:  # noqa: BLE001 - a check that can't run shows nothing
                log.debug("listing who records the mic failed", exc_info=True)   # (often)
                return None

        def look():
            busy.emit(mw.bridge.mic_users, run())
        self._raw_poll.run(look)

    def _on_mic_users(self, apps, now: float | None = None):
        mw = self.mw
        self._raw_looking = False
        if apps is None or mw.engine.direct_stream() is None:
            return
        before = [a.exe for a in self.raw_watch.culprits]
        culprits = self.raw_watch.update(apps, mw.engine.direct_apps(),
                                        time.monotonic() if now is None else now)
        if [a.exe for a in culprits] != before:
            log.info("recording the mic without Onion Board: %s",
                     [a.exe for a in culprits] or "nobody")
            self._show_urgent()

    def discord_problems(self) -> list[str]:
        """What in the running Discord's own settings hurts your sounds (discordcfg),
        worst first; [] when it's fine, not running, or couldn't be read."""
        mw = self.mw
        if not self.discord_found:
            return []
        from soundboard.ui.chatguide import raw_skips
        return self.discord_found[0].problems(raw_skips(mw))

    def _discord_tick(self):
        """Every DISCORD_POLL_MS: while Discord runs, re-read its settings when its
        files changed. On a worker: the process list and the files take a few ms."""
        mw = self.mw
        if self._discord_reading:
            return
        self._discord_reading = True
        last = self._discord_sig
        seen = set(self._talk_seen)

        def run():
            found, sig, talk = [], None, {}
            try:
                from soundboard.ui.chatguide import DISCORD_EXES
                names = {n for _p, n in appaudio._process_table().values()}
                if names & set(DISCORD_EXES):
                    sig = discordcfg.signature()
                    found = None if sig == last else discordcfg.read()
                    talk = _talk_snapshots(found or [], seen)
            except Exception:  # noqa: BLE001 - a check that can't run shows nothing
                log.debug("reading Discord's settings failed", exc_info=True)
            mw.bridge.discord.emit((found, sig, talk))
        self._discord_poll.run(run)

    def _on_discord(self, res):
        mw = self.mw
        found, sig, *more = res   # (found, sig, talk snapshots)
        talk = more[0] if more else {}
        self._discord_reading = False
        self._discord_sig = sig
        if found is None:   # unchanged
            return
        self._remember_talk(found, talk)
        before = self.discord_problems()
        self.discord_found = found
        now = self.discord_problems()
        if now != before:
            log.info("Discord settings: %s", now or "fine")
            self._show_urgent()
        app = mw.appsetctl._setup_app
        if mw.appsetctl._setup_state == "done" and app is not None and app.guide == "discord":
            mw.appsetctl._show_setup("done", app)   # its ticks, live

    def _remember_talk(self, found: list, talk: dict):
        """How you talk in each Discord, as it was set when the board first saw it
        (before it was set up for sounds): what's put back on quit (discordtalk)."""
        mw = self.mw
        dirs = {name: d for d, name in discordcfg.CLIENTS}
        for s in found:
            d = dirs.get(s.client)
            if d is None or d in self._talk_seen:
                continue
            self._talk_seen.add(d)
            if talk.get(d) and mw.cfg.discord_talk.get(d) != talk[d]:
                mw.cfg.discord_talk = {**mw.cfg.discord_talk, d: talk[d]}
                log.info("%s: remembered how you talk there", s.client)
                mw._save_later()

    def discord_quit(self):
        """On quit: put each Discord left set for sounds back the way you talk, or
        (still open) hand it to the helper that does it once Discord closes."""
        cfg = self.mw.cfg
        if not cfg.discord_restore:
            return
        import threading

        from soundboard.mic import discordtalk
        from soundboard.sounds.library import APP_DIR
        saved = dict(cfg.discord_talk)
        out: list = []

        def run():
            out.append(discordtalk.restore(saved, APP_DIR / "discord-backup"))
        t = threading.Thread(target=run, daemon=True, name="discord-restore")
        t.start()
        t.join(DISCORD_QUIT_S)   # files only, normally well under a second
        if out and out[0]:
            log.info("Discord still open (%s): the helper puts it back once it closes",
                     ", ".join(out[0]))
            discordtalk.start_helper(APP_DIR, saved, out[0])

    def _show_urgent(self):
        mw = self.mw
        now = self._urgent_now()
        if now is None:
            mw.urgent_bar.hide()
            return
        key, text, button = now
        mw.urgent_lbl.setText(text)
        mw.urgent_btn.setText(button)
        mw.urgent_btn.setVisible(bool(button))   # a warning with nothing to click
        # Onion Board's own fix: the update card's progress and words, under the reason
        upd = mw.updctl
        board = key.startswith("board") and (upd._downloading or bool(upd._update_err))
        mw.urgent_prog.setVisible(board and mw.updctl._downloading)
        mw.urgent_prog.setValue(mw.updctl._update_pct())
        mw.urgent_sub.setVisible(board)
        if board:
            state = mw.updctl._update_words()   # failed: the reason (Try again is beside it)
            mw.urgent_sub.setText(state[3] if state[0] == "failed"
                                    else " · ".join(filter(None, (state[1], state[2]))))
        mw.urgent_bar.show()
        if mw.appsetctl._setup_state == "offer":
            mw.appsetctl._hide_setup()   # one bar at a time: the warning beats "Set up for it?"

    def _hide_urgent(self):
        now = self._urgent_now()
        if now is not None:
            self._urgent_hidden.add(now[0])
        self._show_urgent()   # the next one, if any

    def _urgent_clicked(self):
        mw = self.mw
        now = self._urgent_now()
        if now is None:
            return
        if now[0].startswith("discord"):
            mw.statusctl.show_chat_guide("discord")
            self._show_urgent()   # fixed meanwhile, or still to do
            return
        if now[0].startswith("board"):
            if mw.updctl._downloading:
                mw.updctl.cancel_update()
            elif mw.updctl._update_file is not None and not mw.updctl._update_err:
                mw.updctl.install_update()
            elif (updates.can_install() and mw.updctl.release is not None
                  and mw.updctl.release.asset_url):
                mw.updctl.download_update()
            else:
                mw.updctl.show_update()
            return
        # Onion Watch: its tab does the updating (and shows how it's going)
        mw.tabs.setCurrentWidget(mw.triggers)
        if (isinstance(mw.triggers, TriggersTab) and mw.triggers.offer is not None
                and not mw.triggers._busy):
            mw.triggers.get()
        mw.watch_offer = None
        self._show_urgent()
