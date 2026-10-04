"""Local control API: lets a Stream Deck (its "API request" / website actions, Bitfocus
Companion, Touch Portal…), AutoHotkey or a script play pads.

Off unless turned on in Settings → Remote. It listens on 127.0.0.1 only, on
Config.api_port, and every request must carry the token shown in Settings, as
`Authorization: Bearer <token>`, an `X-Token: <token>` header, or `?token=<token>`
for tools that can only open a URL. The token is random, stays in config.json (a
Stream Deck button has to keep working after a restart, so it can't change every
launch), is never exported with a backup, and is never logged; Settings can make a
new one. Requests whose Host isn't this PC's loopback are refused (DNS rebinding),
and no CORS headers are sent, so a web page can't read anything back.

Every endpoint takes GET or POST and answers JSON (ENDPOINTS below is the list;
/api/help returns it, so a script or an AI assistant can look it up):

    /api/status                  version, what's playing, category, live / voice / mic
    /api/sounds                  [{id, name, hotkey, categories, playing}]
    /api/categories              ["Memes", ...]
    /api/play?id=… or ?name=…    play a pad (name: exact, any case)
    /api/stop?id=… or ?name=…    stop one sound;  /api/stop alone stops everything
    /api/pause                   pause everything / resume
    /api/random[?category=…]     a random sound (default: the category showing;
                                 category= with nothing after it: any sound)
    /api/last                    play the last sound again
    /api/category?name=… / ?step=next|prev   show a category (name= blank: All)
    /api/volume?set=0-100 / ?step=up|down    the sounds' volume
    /api/live, /api/voice, /api/mic [?on=1|0|toggle]
                                 the Live / Muted switch, the voice changer, "others
                                 hear my mic" (no on=: toggle)
    /api/replay                  save the instant replay as a pad
    /api/help                    this list

The HTTP side runs on its own thread; each request is handed to the UI thread
(`RemoteControl.request`) and answered from there, so it never touches the
window's state from another thread.
"""
from __future__ import annotations

import difflib
import json
import logging
import secrets
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit

from PySide6.QtCore import QObject, Qt, Signal

if TYPE_CHECKING:
    from soundboard.ui.mainwindow import MainWindow

log = logging.getLogger(__name__)

HOST = "127.0.0.1"
DEFAULT_PORT = 7474
ANSWER_S = 3.0          # how long a request waits for the UI thread
IDLE_S = 10.0           # a client that connects and goes quiet is dropped after this
# every endpoint, in the order they're listed (the 404 answer, /api/help, the
# setup prompt and Settings all read this)
ENDPOINTS = {
    "status": "version, what's playing, the category showing, live / voice / mic / volume",
    "sounds": "every sound: [{id, name, hotkey, categories, playing}]",
    "categories": "the category names",
    "play": "play one sound: ?name=Airhorn (exact name, any case) or ?id=…",
    "stop": "stop one sound (?name= or ?id=); with neither, stop everything",
    "pause": "pause everything, or resume if it's all paused",
    "random": "a random sound from ?category=… (default: the one showing; "
              "category= blank: any sound)",
    "last": "play the last sound again",
    "category": "show a category: ?name=Memes (name= blank: All) or ?step=next / prev",
    "volume": "the sounds' volume: ?set=0-100 or ?step=up / down (10 % a step)",
    "live": "the Live / Muted switch (Muted: others hear nothing): ?on=1 / 0 / toggle",
    "voice": "the voice changer on / off: ?on=1 / 0 / toggle",
    "mic": "whether others hear your mic: ?on=1 / 0 / toggle",
    "replay": "save the instant replay (the last seconds you heard) as a new sound",
    "help": "this list",
}
ACTIONS = tuple(ENDPOINTS)


def new_token() -> str:
    return secrets.token_urlsafe(24)


@dataclass
class Job:
    action: str
    params: dict
    done: threading.Event = field(default_factory=threading.Event)
    status: int = 500
    body: object = None
    # a request answered "busy" must not still run later (a retrying Stream Deck
    # would play the sound twice); the lock settles which of the two happens
    lock: threading.Lock = field(default_factory=threading.Lock)
    started: bool = False
    cancelled: bool = False


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False   # Windows: reuse would let two apps share the port


class RemoteControl(QObject):
    """Starts / stops the server. `dispatch(action, params) -> (status, body)` runs on
    the UI thread for every authorised request."""
    request = Signal(object)

    def __init__(self, dispatch, parent=None):
        super().__init__(parent)
        self.dispatch = dispatch
        self.token = ""
        self.port = 0
        self.error = ""
        self._server: _Server | None = None
        self.request.connect(self._on_request, Qt.QueuedConnection)

    @property
    def running(self) -> bool:
        return self._server is not None

    def start(self, port: int, token: str) -> bool:
        """(Re)start on `port`. False (and `error` says why) if it can't listen."""
        self.stop()
        self.token, self.port, self.error = token, int(port), ""
        if not token:
            self.error = "no token"
            return False
        try:
            srv = _Server((HOST, self.port), _handler_for(self))
        except (OverflowError, ValueError) as e:   # a port outside 0-65535
            self.error = f"port {self.port} isn't a valid port — pick one from 1024 to 65535"
            log.warning("control API couldn't listen on %s:%s: %s", HOST, self.port, e)
            return False
        except OSError as e:
            self.error = (f"port {self.port} is already in use — pick another"
                          if getattr(e, "winerror", None) == 10048 or e.errno in (98, 10048)
                          else str(e))
            log.warning("control API couldn't listen on %s:%s: %s", HOST, self.port, e)
            return False
        self._server = srv
        self.port = srv.server_address[1]   # (port 0 = any free one, for the tests)
        threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.25},
                         daemon=True, name="control-api").start()
        log.info("control API listening on %s:%s", HOST, self.port)
        return True

    def stop(self):
        srv, self._server = self._server, None
        if srv is not None:
            srv.shutdown()
            srv.server_close()
            log.info("control API stopped")

    def _on_request(self, job: Job):
        with job.lock:
            if job.cancelled:
                return
            job.started = True
        try:
            job.status, job.body = self.dispatch(job.action, job.params)
        except Exception:  # noqa: BLE001 - a bad request must never take the app down
            log.exception("control API request %s failed", job.action)
            job.status, job.body = 500, {"error": "internal error (see the log)"}
        job.done.set()

    # ------------------------------------------------------------------ requests
    def authorised(self, headers, query: dict) -> bool:
        given = ""
        auth = headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            given = auth[7:].strip()
        given = given or headers.get("X-Token", "") or (query.get("token") or [""])[0]
        return bool(self.token) and secrets.compare_digest(given.encode(), self.token.encode())

    def host_ok(self, host: str) -> bool:
        return host in (f"{HOST}:{self.port}", f"localhost:{self.port}", HOST, "localhost")


def _handler_for(ctl: RemoteControl):
    class Handler(BaseHTTPRequestHandler):
        server_version = "OnionBoardAPI"
        sys_version = ""
        timeout = IDLE_S

        def log_message(self, fmt, *args):   # the query string may hold the token
            pass

        def _answer(self, status: int, body):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _go(self):
            url = urlsplit(self.path)
            query = parse_qs(url.query, keep_blank_values=True)
            if not ctl.host_ok(self.headers.get("Host", "")):
                return self._answer(403, {"error": "wrong host"})
            if not ctl.authorised(self.headers, query):
                return self._answer(401, {"error": "missing or wrong token"})
            action = url.path.strip("/").removeprefix("api/").removeprefix("api")
            if action not in ACTIONS:
                return self._answer(404, {"error": "unknown endpoint",
                                          "endpoints": [f"/api/{a}" for a in ACTIONS]})
            params = {k: v[0] for k, v in query.items() if k != "token"}
            job = Job(action, params)
            ctl.request.emit(job)
            if not job.done.wait(ANSWER_S):
                with job.lock:
                    job.cancelled = not job.started
                if job.cancelled:
                    return self._answer(503, {"error": "the app is busy, try again"})
                job.done.wait()   # it got going just now: answer what it did
            self._answer(job.status, job.body)

        do_GET = do_POST = _go

    return Handler


# --------------------------------------------------------------------------- the app side

def on_value(params: dict, now: bool) -> bool | None:
    """?on=1 / 0 / toggle (or nothing: toggle) -> the new state; None if it's neither."""
    v = (params.get("on") or "toggle").strip().lower()
    if v in ("1", "true", "on", "yes"):
        return True
    if v in ("0", "false", "off", "no"):
        return False
    return not now if v == "toggle" else None


BAD_ON = {"error": "on= takes 1, 0 or toggle"}


def dispatch(mw: MainWindow, action: str, params: dict) -> tuple[int, object]:
    """Carry out one request on the window (UI thread)."""
    cfg = mw.cfg
    playing = mw.engine.playing()
    if action == "help":
        return 200, {"endpoints": {f"/api/{a}": d for a, d in ENDPOINTS.items()},
                     "key": "send it as ?token=…, an X-Token header or Authorization: "
                            "Bearer …"}
    if action == "status":
        from soundboard import __version__
        return 200, {"version": __version__, "category": cfg.category,
                     "playing": [s for s in playing if s in mw.pads],
                     "paused": bool(playing) and all(p for _, p in playing.values()),
                     "live": bool(mw.engine.sending),
                     "voice": mw.voice.fx.btn_power.isChecked(),
                     "mic": bool(cfg.mic_enabled),
                     "volume": mw.vol_sound.spin.value()}
    if action == "sounds":
        return 200, [{"id": m.id, "name": m.name, "hotkey": m.hotkey,
                      "categories": list(m.tags), "playing": m.id in playing}
                     for m in cfg.sounds]
    if action == "categories":
        return 200, list(cfg.categories)
    if action == "pause":
        return 200, {"paused": mw.engine.pause_all()}
    if action == "random":
        cat = params.get("category")
        if cat:
            cat = find_category(cfg, cat)
            if cat is None:
                return 404, {"error": f"no category called {params['category']!r}",
                             "categories": list(cfg.categories)}
        sid = mw.play_random(cat)
        if sid is None:
            return 404, {"error": "no sound to play there"}
        return 200, {"playing": sid, "name": mw.meta(sid).name}
    if action == "last":
        sid = getattr(mw, "_last_sid", None)
        if sid is None or mw.meta(sid) is None:
            return 404, {"error": "nothing has played yet"}
        if sid not in mw.audio:
            return 409, {"error": "that sound hasn't loaded (yet)"}
        mw.play(sid)
        return 200, {"playing": sid, "name": mw.meta(sid).name}
    if action == "category":
        step = (params.get("step") or "").strip().lower()
        if step:
            if step not in ("next", "prev", "previous"):
                return 400, {"error": "step= takes next or prev"}
            mw.step_category(1 if step == "next" else -1)
        elif "name" in params:
            name = params["name"].strip()
            match = find_category(cfg, name)
            if name and name.lower() != "all" and match is None:
                return 404, {"error": f"no category called {name!r}",
                             "categories": list(cfg.categories)}
            mw.set_category(match or "")
        else:
            return 400, {"error": "say which: ?name=… or ?step=next / prev"}
        return 200, {"category": cfg.category}
    if action == "volume":
        spin = mw.vol_sound.spin
        step = (params.get("step") or "").strip().lower()
        if "set" in params:
            try:
                new = round(float(params["set"]))
            except ValueError:
                return 400, {"error": "set= takes a number, 0-100"}
        elif step in ("up", "down", "+", "-"):
            new = (round(spin.value() / 10) + (1 if step in ("up", "+") else -1)) * 10
        else:
            return 400, {"error": "say how: ?set=0-100 or ?step=up / down"}
        spin.setValue(min(max(new, 0), spin.maximum()))   # -> set_option("sound_vol")
        return 200, {"volume": spin.value()}
    if action == "live":
        on = on_value(params, bool(mw.engine.sending))
        if on is None:
            return 400, BAD_ON
        mw.set_sending(on)
        return 200, {"live": bool(mw.engine.sending)}
    if action == "voice":
        on = on_value(params, mw.voice.fx.btn_power.isChecked())
        if on is None:
            return 400, BAD_ON
        mw._set_voice(on)
        return 200, {"voice": mw.voice.fx.btn_power.isChecked()}
    if action == "mic":
        on = on_value(params, bool(cfg.mic_enabled))
        if on is None:
            return 400, BAD_ON
        mw.chk_mic.setChecked(on)   # -> on_mic_toggle
        return 200, {"mic": bool(cfg.mic_enabled)}
    if action == "replay":
        from soundboard.engine import SR
        if len(mw.replay.clip()) < int(0.2 * SR):
            return 409, {"error": mw.replay.error or "nothing has played on this PC lately"}
        mw.save_replay()
        return 200, {"saved": True}
    # play / stop: one sound, by id or name
    if action == "stop" and not ("id" in params or "name" in params):
        mw.stop_all()
        return 200, {"stopped": "all"}
    m = find_sound(mw, params)
    if m is None:
        if not params:
            return 400, {"error": "say which: ?id=… or ?name=…"}
        body = {"error": "no such sound"}
        if params.get("name"):   # a typo'd button: say what it probably meant
            close = difflib.get_close_matches(params["name"].strip(),
                                              [s.name for s in cfg.sounds], 3, 0.5)
            if close:
                body["did_you_mean"] = close
        return 404, body
    if action == "stop":
        mw.engine.stop(m.id)
        return 200, {"stopped": m.id}
    if m.id not in mw.audio:
        return 409, {"error": "that sound hasn't loaded (yet)"}
    mw.play(m.id)
    return 200, {"playing": m.id, "name": m.name}


def find_category(cfg, name: str) -> str | None:
    """A category by name, any case; None if there's no such one."""
    name = name.strip().lower()
    return next((c for c in cfg.categories if c.lower() == name), None)


def find_sound(mw: MainWindow, params: dict):
    if params.get("id"):
        return mw.meta(params["id"])
    name = (params.get("name") or "").strip().lower()
    if name:
        return next((m for m in mw.cfg.sounds if m.name.lower() == name), None)
    return None


def apply(mw: MainWindow, ctl: RemoteControl) -> str:
    """Start or stop the server to match the settings. Returns an error ("" if fine)."""
    cfg = mw.cfg
    if not cfg.api_enabled:
        ctl.stop()
        return ""
    if not cfg.api_token:
        cfg.api_token = new_token()
        cfg.save()
    if ctl.running and ctl.port == cfg.api_port and ctl.token == cfg.api_token:
        return ""
    ctl.start(cfg.api_port, cfg.api_token)
    return ctl.error


# --------------------------------------------------------------------------- AI setup prompt

KEY_PLACEHOLDER = "YOUR-KEY"
PROMPT_SOUNDS = 120     # a big library: list this many names, the AI can ask for the rest


def setup_prompt(cfg, port: int, token: str = "") -> str:
    """A message to paste into ChatGPT / Claude / any AI assistant so it can walk
    someone through wiring their Stream Deck, Streamer.bot, Touch Portal… to the
    control API: the address, every endpoint, their own sounds and categories, and
    how each common tool sends a request. Without `token` the key is a placeholder
    the person fills in themselves."""
    from urllib.parse import quote

    key = token or KEY_PLACEHOLDER
    base = f"http://{HOST}:{port}"
    sounds = list(cfg.sounds)
    names = [f"- {m.name}" + (f"  (categories: {', '.join(m.tags)})" if m.tags else "")
             for m in sounds[:PROMPT_SOUNDS]]
    if len(sounds) > PROMPT_SOUNDS:
        names.append(f"- … and {len(sounds) - PROMPT_SOUNDS} more (GET /api/sounds lists "
                     "them all)")
    example = sounds[0].name if sounds else "Airhorn"
    cat = cfg.categories[0] if cfg.categories else "Memes"
    endpoints = "\n".join(f"- /api/{a} — {d}" for a, d in ENDPOINTS.items())
    key_note = ("" if token else
                f"\nMy key isn't in this message: write {KEY_PLACEHOLDER} wherever it goes "
                "and remind me to replace it with the key from Settings → Remote (click "
                "Show).\n")
    return f"""\
I use Onion Board, a free Windows soundboard. Its "Remote control" feature lets other \
programs on my PC control it over a small local HTTP API. Please help me set up my \
streaming tools to use it. Ask me first which tools I use (Stream Deck, Streamer.bot, \
Touch Portal, Bitfocus Companion, SAMMI, Mix It Up, AutoHotkey, a macro pad…) and what \
I want the buttons / triggers to do, then give me exact click-by-click steps for each \
one, with the full URLs ready to copy.

HOW THE API WORKS
- Address: {base}  (it only listens on this PC: tools on another computer or phone \
can't reach it, so they must run on this PC)
- Every request needs my key, as ?token=KEY in the URL (simplest: works anywhere a URL \
can be opened), an X-Token: KEY header, or Authorization: Bearer KEY.
- GET or POST both work; every answer is JSON. The Host header must be 127.0.0.1 or \
localhost.
- Sound and category names must match exactly (any case) and be URL-encoded: a space is \
%20, & is %26. A wrong name answers 404 with "did_you_mean".
- Errors: 401 = wrong / missing key, 404 = no such sound / category, 409 = not \
loaded yet, 503 = the app was busy (safe to retry). If nothing answers at all, Onion \
Board isn't running or "Enable remote control" is off.
- Test it first by opening {base}/api/status?token={key} in a browser.
{key_note}
ENDPOINTS
{endpoints}

EXAMPLES
- Play a sound: {base}/api/play?name={quote(example)}&token={key}
- Random sound from a category: {base}/api/random?category={quote(cat)}&token={key}
- Stop everything: {base}/api/stop?token={key}
- Panic button (others hear nothing until pressed again): \
{base}/api/live?on=toggle&token={key}
- Voice changer on / off: {base}/api/voice?on=toggle&token={key}

WHERE EACH TOOL SENDS A REQUEST (as far as I know — correct me if a tool has changed)
- Elgato Stream Deck app: System → Website action, paste the URL, tick "GET request in \
background" so no browser opens. (Or a free "API Request" plugin from the Marketplace.)
- Streamer.bot: an Action with the sub-action Core → Network → Fetch URL; triggers such \
as Twitch → Channel Reward → Reward Redemption, chat commands, cheers / bits, raids, \
follows. Fetch URL runs in the background.
- Touch Portal: the "HTTP Get" action (or a web-request plugin).
- Bitfocus Companion: the "Generic HTTP" connection, a GET action with the full URL \
(Companion must run on this PC).
- SAMMI / Mix It Up: their "HTTP request" / "Web Request" command, GET.
- AutoHotkey v2: whr := ComObject("WinHttp.WinHttpRequest.5.1"), \
whr.Open("GET", url), whr.Send() — bound to a key.
- Anything else that can open a URL or run a command: curl -s "URL".

MY SETUP RIGHT NOW
- Port: {port}
- Categories: {", ".join(cfg.categories) or "(none yet: every sound is in All)"}
- Sounds ({len(sounds)}):
{chr(10).join(names) or "- (none yet)"}

Keep the steps beginner-friendly. Don't suggest exposing the API to the internet, \
port-forwarding it or running it on another machine: it's meant for this PC only.
"""
