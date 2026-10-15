"""Settings → Connection and Updates: going online, the activity log, updates."""
from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget)
from shiboken6 import isValid as qt_valid

from soundboard import errors, theme, usage, ytdl
from soundboard.i18n import _
from soundboard.ui import busy
from soundboard.ui.settingspages import Page
from soundboard.wheelguard import no_wheel

# the yt-dlp buttons' jobs (ytdl.update, reset, force_newest) as the count's names
YTDLP_COUNTS = {"update": "ytdlp-update", "reset": "ytdlp-reinstall",
                "force_newest": "ytdlp-force"}


class _Relay(QObject):
    """Carries a background job's result back to the UI thread."""
    done = Signal(str)


class _ProgressRelay(_Relay):
    """A _Relay that also carries progress (bytes done, bytes in all; 0 = unknown)."""
    progress = Signal(int, int)


class ConnectionPage(Page):
    """Settings → Connection and Updates: going online, the activity log, updates."""

    def _connection(self):
        w, v = self._page()
        v.addWidget(self.dlg.privacy._offline_card(self._connection_card()))   # Offline: no use
        v.addWidget(self._activity_card())
        v.addStretch(1)
        return w

    def _connection_card(self):
        """Connection: Direct, through a proxy, or through the app's own Tor
        (soundboard.net, soundboard.tor). Applies at once; a proxy or Tor that can't be
        reached makes requests fail, never go direct."""
        from PySide6.QtWidgets import QButtonGroup, QLineEdit, QRadioButton


        from soundboard import net, tor, torget
        cfg = self.mw.cfg
        card, cv = self._card(
            _("Connection"),
            _("Through a proxy or Tor, everything the app fetches (searches, downloads, radio, "
              "updates) goes through it, and site names are looked up there, not on this PC. If "
              "it can't be reached, nothing is fetched: the app never quietly goes direct. This "
              "PC's own addresses (127.0.0.1) stay direct."), icon="tor")
        direct = QRadioButton(_("Direct"))
        direct.setToolTip(_("Connect straight to each site"))
        via = QRadioButton(_("Through a proxy"))
        via.setToolTip(_("A proxy of your own (or one your VPN app offers)"))
        use_tor = QRadioButton("Tor")
        use_tor.setToolTip(_("The app's own Tor: sites and radio stations don't see your address"))
        group = QButtonGroup(card)
        row = QHBoxLayout()
        for b in (direct, via, use_tor):
            group.addButton(b)
            row.addWidget(b)
        row.addStretch(1)
        cv.addLayout(row)

        # ---- Get Tor: the app doesn't ship it (soundboard.torget)
        get_box = QWidget()
        row = QHBoxLayout(get_box)
        row.setContentsMargins(0, 0, 0, 0)
        get_note = QLabel()
        get_note.setObjectName("hint")
        get_note.setWordWrap(True)
        row.addWidget(get_note, 1)
        get = QPushButton(_("Get Tor"))
        get.setProperty("tip", _("Download Tor {version} from the Tor Project "
                                 "(dist.torproject.org), the way the Connection setting says",
                                 version=torget.VERSION))
        get.setToolTip(get.property("tip"))
        row.addWidget(get)
        cv.addWidget(get_box)

        def show_get(msg: str = ""):
            have = tor.available()
            outdated = (have and tor.bundle_dir() == torget.bin_dir()
                        and not torget.installed())
            use_tor.setEnabled(have)
            use_tor.setToolTip(
                _("The app's own Tor: sites and radio stations don't see your address")
                if have else tor.not_installed())
            if not busy.is_busy(get):
                get.setText(_("Update Tor") if outdated else _("Get Tor"))
            get_box.setVisible(bool(msg) or busy.is_busy(get) or not have or outdated)
            get_note.setText(msg or (
                _("A newer Tor ({version}) is ready to download.", version=torget.VERSION)
                if outdated else
                _("To use Tor, get it first: about 22 MB from the Tor Project, checked "
                  "before it's used. {blocked_hint}", blocked_hint=torget.blocked_hint())))

        # ---- proxy
        proxy_box = QWidget()
        row = QHBoxLayout(proxy_box)
        row.setContentsMargins(0, 0, 0, 0)
        addr = QLineEdit(cfg.net_proxy)
        addr.setPlaceholderText(_("socks5h://127.0.0.1:9050  or  http://host:8080"))
        addr.setToolTip(_("A SOCKS5 proxy (host names are looked up by the proxy) or an HTTP "
                          "proxy. Add user:password@ before the host if it needs a login."))
        row.addWidget(addr, 1)
        test = QPushButton(_("Test"))
        test.setToolTip(_("Connect to GitHub through this proxy (only to see that it works)"))
        row.addWidget(test)
        cv.addWidget(proxy_box)

        # ---- Tor
        tor_box = QWidget()
        tv = QVBoxLayout(tor_box)
        tv.setContentsMargins(0, 0, 0, 0)
        about = QLabel(_("Tor sends everything through three volunteer computers around the "
                         "world, so the sites you search and download from and the radio "
                         "stations you play see a Tor address, not yours. It's slower, and "
                         "YouTube often turns Tor away: the app then tries other Tor routes, and "
                         "only goes without Tor if you click to."))
        about.setObjectName("hint")
        about.setWordWrap(True)
        tv.addWidget(about)
        row = QHBoxLayout()
        tor_state = QLabel()
        tor_state.setWordWrap(True)
        row.addWidget(tor_state, 1)
        newnym = QPushButton(_("New identity"))
        newnym.setToolTip(_("New connections go out through a different Tor route, so sites see "
                            "a different address"))
        row.addWidget(newnym)
        tv.addLayout(row)
        row = QHBoxLayout()
        hide = QCheckBox(_("Hide that I'm using Tor"))
        hide.setChecked(bool(cfg.tor_bridges))
        row.addWidget(hide)
        kind = QComboBox()
        kind.addItem(_("Snowflake"), "snowflake")
        kind.addItem("obfs4", "obfs4")
        kind.setItemData(0, _("Looks like a video call"), Qt.ItemDataRole.ToolTipRole)
        kind.setItemData(1, _("Looks like random noise"), Qt.ItemDataRole.ToolTipRole)
        kind.setCurrentIndex(max(0, kind.findData(cfg.tor_bridges or tor.DEFAULT_BRIDGE)))
        kind.setToolTip(_("If one doesn't connect, try the other"))
        no_wheel(kind)
        row.addWidget(kind)
        row.addStretch(1)
        tv.addLayout(row)
        hide_hint = QLabel(_("Disguises the connection so your internet provider can't easily "
                             "tell it's Tor. Helps where Tor is blocked or frowned on. It's "
                             "slower, and connecting can take a few minutes."))
        hide_hint.setObjectName("hint")
        hide_hint.setWordWrap(True)
        hide_hint.setContentsMargins(26, 0, 0, 0)   # under the box's text, not its tick
        tv.addWidget(hide_hint)
        cv.addWidget(tor_box)

        note = QLabel()
        note.setObjectName("hint")
        note.setWordWrap(True)
        cv.addWidget(note)
        {net.TOR: use_tor, net.PROXY: via}.get(cfg.net_mode, direct).setChecked(True)

        def show():
            if not qt_valid(note):
                return
            proxy_box.setVisible(via.isChecked())
            addr.setEnabled(via.isChecked())
            test.setEnabled(via.isChecked())
            tor_box.setVisible(use_tor.isChecked())
            note.setVisible(not use_tor.isChecked())
            kind.setEnabled(hide.isChecked())
            t = tor.manager()
            tor_state.setText(t.status_text())
            color = {tor.READY: "ok", tor.FAILED: "error"}.get(t.state)
            tor_state.setStyleSheet(f"color: {theme.status(color)}" if color else "")
            if not busy.is_busy(newnym):
                newnym.setEnabled(t.state == tor.READY)
            if via.isChecked():
                try:
                    net.parse(addr.text())
                except ValueError as e:
                    note.setText(_("{error}. Until it's fixed, nothing goes online.",
                                   error=e))
                    return
            note.setText(_("Now: {connection}.", connection=net.describe()))

        def apply():
            mode = (net.TOR if use_tor.isChecked() else
                    net.PROXY if via.isChecked() else net.DIRECT)
            text = addr.text().strip()
            bridges = kind.currentData() if hide.isChecked() else ""
            if (mode, text, bridges) != (cfg.net_mode, cfg.net_proxy, cfg.tor_bridges):
                self.mw.set_option("net_mode", mode)     # saves
                self.mw.set_option("net_proxy", text)
                self.mw.set_option("tor_bridges", bridges)
                tor.configure_from(cfg)                  # before net: its gate needs it
                net.configure(mode, text)
                if mode == net.TOR:
                    tor.manager().start()   # picked here: connect now and show how far
            show()

        for b in (direct, via, use_tor):
            b.toggled.connect(lambda on: on and apply())
        addr.editingFinished.connect(apply)
        hide.toggled.connect(lambda _on: apply())
        kind.currentIndexChanged.connect(lambda _i: apply())
        status = tor.qt_status()
        status.changed.connect(show)

        def unhook(*__):
            try:
                status.changed.disconnect(show)
            except (RuntimeError, TypeError):
                pass
        card.destroyed.connect(unhook)

        def run_newnym():
            release = busy.hold(newnym, _("Changing…"))
            relay = _Relay(self.mw)   # outlives this window if it's closed meanwhile

            def finish(msg):
                relay.deleteLater()
                ok = msg == tor.newnym_ok()
                release(_("✓ Changed") if ok else _("✗ Failed"))
                if qt_valid(tor_state):
                    tor_state.setText(msg)

            relay.done.connect(finish)
            threading.Thread(target=lambda: relay.done.emit(tor.new_identity()),
                             daemon=True, name="tor-newnym").start()
        newnym.clicked.connect(run_newnym)

        def run_get():
            def progress(text):
                if qt_valid(get_note):
                    get_note.setText(text)

            def finish(err):
                if qt_valid(get_note):
                    show_get(err or _("Tor {version} is ready: pick Tor above to use it.",
                                      version=torget.VERSION))
                    show()
                    self._net_sync()
            self._tor_get(get, progress, finish, "Settings > Connection")

        get.clicked.connect(run_get)

        def run_test():
            text = addr.text()
            release = busy.hold(test, _("Testing…"))
            relay = _Relay(self.mw)   # outlives this window if it's closed meanwhile
            worked = []   # set by the thread before it emits: not read from the message

            def finish(msg):
                relay.deleteLater()
                release(_("✓ Works") if worked else _("✗ Failed"))
                if qt_valid(note):
                    note.setText(msg)

            relay.done.connect(finish)

            def run():
                from soundboard import netlog
                netlog.cause(net.TEST, "You clicked Test (Settings > Connection)")
                try:
                    msg = net.test(text)
                    worked.append(True)
                except (ValueError, OSError) as e:
                    msg = _("It didn't work: {error}", error=errors.plain(e))
                relay.done.emit(msg)
            threading.Thread(target=run, daemon=True, name="proxy-test").start()
        test.clicked.connect(run_test)
        (self.dlg.net_direct, self.dlg.net_via, self.dlg.net_addr,
         self.dlg.net_test) = direct, via, addr, test
        self.dlg.net_tor, self.dlg.net_hide, self.dlg.net_bridge = use_tor, hide, kind
        self.dlg.net_tor_state, self.dlg.net_newnym = tor_state, newnym
        self.dlg.net_get, self.dlg.net_get_note = get, get_note

        def tor_got():   # Tor got from Data & quality: Get Tor here says so too
            if qt_valid(get_note):
                show_get()
        self.dlg._net_show_get = tor_got
        self.dlg.net_note = note
        show_get()
        show()
        self._net_sync()   # Get Tor switched off: greyed, with the reason
        return card

    def _tor_get(self, button: QPushButton, progress, done, where: str):
        """Download Tor (soundboard.torget) on a worker, `button` busy meanwhile: Get Tor
        here and Update Tor on Data & quality. `progress(text)` gets how far it is,
        `done(error)` an empty error when it worked; both on the UI thread."""
        import logging

        from soundboard import tor, torget
        release = busy.hold(button, _("Downloading…"))
        relay = _ProgressRelay(self.mw)   # outlives this window if it's closed meanwhile

        def moved(got, total):
            progress(_("Downloading Tor… {done:.1f} of {total:.1f} MB",
                       done=got / 1e6, total=total / 1e6) if total else
                     _("Downloading Tor… {done:.1f} MB", done=got / 1e6))

        def finish(err):
            relay.deleteLater()
            release(_("✗ Failed") if err else _("✓ Got Tor"))
            for refresh in ("_net_show_get", "_helpers_refresh"):   # both pages follow,
                fn = getattr(self.dlg, refresh, None)
                if fn is not None:
                    fn()
            done(err)   # then the clicked one says how it went

        def work():
            from soundboard import netlog
            netlog.cause(torget.FEATURE, f"You clicked to download Tor ({where})")
            try:
                # a running Tor may have carried the download: stopped before its
                # files are swapped, the next connection starts the new one
                torget.get(relay.progress.emit, before_unpack=tor.shutdown)
                relay.done.emit("")
            except torget.GetError as e:
                relay.done.emit(errors.plain(e))
            except Exception as e:  # noqa: BLE001 - shown, never a stuck button
                logging.getLogger(__name__).exception("Get Tor failed")
                relay.done.emit(_("Couldn't get Tor ({error}).", error=errors.plain(e)))

        relay.progress.connect(moved)
        relay.done.connect(finish)
        threading.Thread(target=work, daemon=True, name="tor-get").start()

    def _activity_card(self):
        """Network activity: every connection the app has made (soundboard.netlog)."""
        from soundboard.ui.netactivity import NetActivity
        card, cv = self._card(_("Network activity"), icon="list")
        self.dlg.net_activity = NetActivity(card)
        cv.addWidget(self.dlg.net_activity)
        self.dlg.netlog_keep_box = self._option(
            cv, _("Keep a history between starts"),
            _("Saves this list on this PC (network-activity.jsonl in the app's folder) and shows "
              "it again next time (the last 1000; Totals adds up all of it). Nothing is sent "
              "anywhere. Unticking it deletes the saved file; Clear empties it."),
            self.mw.cfg.netlog_keep, self._set_netlog_keep)
        self.dlg.app_log_box = self._option(
            cv, _("Keep an app log"),
            _("The app writes what it does to onionboard.log in its folder (3 MB at most), "
              "so a problem can be looked into. It can name a site a download or radio "
              "station failed on. Nothing is sent anywhere. Unticking it stops the log and "
              "deletes it."),
            self.mw.cfg.app_log, self._set_app_log)
        return card

    def _set_app_log(self, on: bool):
        from soundboard import applog
        self.mw.set_option("app_log", on)
        applog.keep(on)

    def _set_netlog_keep(self, on: bool):
        from soundboard import library, netlog
        self.mw.set_option("netlog_keep", on)
        netlog.keep(library.APP_DIR / netlog.FILE_NAME if on else None)
        self.dlg.net_activity.refresh(force=True)

    def _updates(self):
        w, v = self._page()
        v.addWidget(self._updates_card())
        v.addWidget(self.dlg.privacy._tools_card())
        v.addStretch(1)
        return w

    # ------------------------------------------------------------------ app updates
    def _updates_card(self):
        from soundboard import __version__, updates
        hint = (_("This is Onion Board {version}. With the box ticked it asks GitHub whether "
                  "a newer version is out each time it starts and every hour after, and tells "
                  "you (with a banner if it's an important fix). Every update is checked "
                  "against the file GitHub lists. Your sounds and settings are kept.",
                  version=__version__)
                if updates.can_install() else
                _("This is Onion Board {version}. With the box ticked it asks GitHub every "
                  "few hours whether a newer version is out and tells you (with a banner if "
                  "it's an important fix). This copy runs from source, so it only tells you: "
                  "update it with git pull.", version=__version__))
        card, cv = self._card(_("App updates"), hint, icon="reload")
        chk = self._option(cv, _("Check for updates"),
                           _("Tell me when a new version is out."), self.mw.cfg.update_check,
                           self._updates_optin)
        self.dlg.upd_chk = chk
        if updates.can_install():   # (from source: git pull)
            auto = self._option(cv, _("Install updates by themselves"),
                                _("When Onion Board starts and a new version is out, it "
                                  "downloads it and restarts to install it, unless a sound is "
                                  "playing."), self.mw.cfg.update_auto,
                                lambda on: self.mw.set_option("update_auto", on))
            self.dlg.upd_auto = auto   # greyed with the check off (_net_sync)
            chk.toggled.connect(lambda _on: self._net_sync())
        row = QHBoxLayout()
        self.dlg.upd_label = QLabel()
        self.dlg.upd_label.setObjectName("hint")
        self.dlg.upd_label.setWordWrap(True)
        # the button first, its result beside it: on the right with nothing yet to
        # say, it sat on a line of its own far from everything else
        self.dlg.upd_btn = QPushButton(_("Check now"))
        self.dlg.upd_btn.clicked.connect(self._updates_check)
        row.addWidget(self.dlg.upd_btn)
        row.addWidget(self.dlg.upd_label, 1)
        cv.addLayout(row)
        self.mw.update_done.connect(self._updates_done)
        # downloading, ready or failed: the same words as the side bar's update card
        self.mw.update_state.connect(self._updates_state)
        self.dlg._upd_wired = True   # done() unhooks only what was hooked
        self._updates_state()
        self._net_sync()   # off in Settings > Privacy: greyed, with the reason
        return card

    def _updates_optin(self, on: bool):
        self.mw.set_option("update_check", on)
        if on:
            self.mw.updctl.check_updates(why="You turned on update checks")

    def _updates_check(self):
        if busy.is_busy(self.dlg.upd_btn) or not self.dlg.upd_btn.isEnabled():
            return
        self.dlg._upd_asked = True
        busy.set_busy(self.dlg.upd_btn, True)
        self.dlg.upd_label.setText(_("Checking…"))
        self.mw.updctl.check_updates(force=True, why="You clicked Check now (Settings > Updates)")

    def _updates_done(self, rel, err: str):
        if not qt_valid(self.dlg.upd_label):
            return
        busy.set_busy(self.dlg.upd_btn, False)
        self._net_sync()
        asked, self.dlg._upd_asked = getattr(self.dlg, "_upd_asked", False), False
        if err:
            self.dlg.upd_label.setText(_("Couldn't check: {error}", error=errors.plain(err)))
        elif rel is None:
            # a check the user didn't ask for may not have asked GitHub at all (done
            # today already, or the newer version was skipped): don't claim anything
            if asked:
                self.dlg.upd_label.setText(_("You have the newest version."))
        else:
            self.dlg.upd_label.setText(_("Version {version} is out.", version=rel.version))

    def _updates_state(self):
        if not qt_valid(self.dlg.upd_label):
            return
        status = self.mw.updctl.update_status() if self.mw.updctl.release is not None else ""
        if status and (self.mw.updctl._downloading or self.mw.updctl._update_err
                       or self.mw.updctl._update_file is not None):
            self.dlg.upd_label.setText(status)

    # ------------------------------------------------------------------ yt-dlp
    def _ytdlp_buttons(self) -> list[QPushButton]:
        """Update now, Reinstall and Force update (Updates > Helper programs), once
        built."""
        return [b for b in getattr(self.dlg, "ytdlp_btns", ()) if qt_valid(b)]

    def _ytdlp_say(self, msg: str):
        """How the update is going, on yt-dlp's row."""
        say = getattr(self.dlg, "_ytdlp_row_say", None)
        if say is not None:
            say(msg)

    def _ytdlp_run(self, job, button: str = "", where: str = "Settings > Updates"):
        """Update now / Reinstall / Force update: `job` (ytdl.update, ytdl.reset or
        ytdl.force_newest) on a worker, all the yt-dlp buttons busy meanwhile."""
        buttons = self._ytdlp_buttons()
        if any(busy.is_busy(b) or not b.isEnabled() for b in buttons):
            return
        from soundboard import netlog
        netlog.cause(ytdl.UPDATE_FEATURE, f"You clicked {button} ({where})"
                     if button else "You asked to update the downloader")
        for b in buttons:
            busy.set_busy(b, True)
        usage.used(YTDLP_COUNTS.get(getattr(job, "__name__", ""), "ytdlp-update"))
        self._ytdlp_say(_("Working…"))
        relay = _Relay(self.mw)   # outlives this window if it's closed meanwhile

        def finish(msg):
            relay.deleteLater()
            for b in self._ytdlp_buttons():
                busy.set_busy(b, False)
            self._net_sync()
            say = getattr(self.dlg, "_ytdlp_row_say", None)
            if say is not None:
                say(msg, done=True)

        relay.done.connect(finish)

        def run():
            try:
                msg = job()
            except Exception as e:  # noqa: BLE001 - offline, PyPI down…
                usage.used("ytdlp-failed")   # the name only, never the error
                msg = _("Couldn't update: {error}.", error=errors.plain(e))
            relay.done.emit(msg)
        threading.Thread(target=run, daemon=True, name="ytdlp-settings").start()

    def _net_sync(self):
        """Grey out what's under a switch that's off (everything, in Offline mode), and
        the buttons on other pages that would go online for it."""
        from soundboard import net, torget
        body = getattr(self.dlg, "_net_body", None)   # None until its page is first shown
        if body is not None:
            if not qt_valid(body):
                return
            body.setVisible(not net.offline())   # Offline mode: only its own box
            for key, sub in self.dlg._net_subs.items():
                sub.setEnabled(key not in self.mw.cfg.net_off)
        for keys, attr in ((("app_update",), "upd_btn"), (("app_update",), "upd_chk"),
                           (("ytdlp_update",), "ytdlp_auto_box")):
            w = getattr(self.dlg, attr, None)
            if w is not None and qt_valid(w):
                w.setEnabled(all(net.allowed(k) for k in keys))
                w.setToolTip("" if w.isEnabled() else net.off_message(keys[0]))
        auto = getattr(self.dlg, "upd_auto", None)   # nothing to install without the check
        if auto is not None and qt_valid(auto):
            auto.setEnabled(net.allowed("app_update") and self.mw.cfg.update_check)
        for b in self._ytdlp_buttons():
            b.setEnabled(net.allowed("ytdlp_update"))
            b.setToolTip(b.property("tip") if b.isEnabled()
                         else net.off_message("ytdlp_update"))
        for attr in ("net_get", "tor_row_btn"):   # Get Tor here, Update Tor on Data & quality
            b = getattr(self.dlg, attr, None)
            if b is not None and qt_valid(b) and not busy.is_busy(b):
                b.setEnabled(net.allowed(torget.FEATURE))
                b.setToolTip(b.property("tip") if b.isEnabled()
                             else net.off_message(torget.FEATURE))
        self.dlg.privacy._offline_sync()
