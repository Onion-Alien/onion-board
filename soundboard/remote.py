"""Local control API: lets a Stream Deck (its "API request" / website actions, Bitfocus
Companion, Touch Portal…), AutoHotkey or a script play pads.

Off unless turned on in Settings → General. It listens on 127.0.0.1 only, on
Config.api_port, and every request must carry the token shown in Settings, as
`Authorization: Bearer <token>`, an `X-Token: <token>` header, or `?token=<token>`
for tools that can only open a URL. The token is random, stays in config.json (a
Stream Deck button has to keep working after a restart, so it can't change every
launch), is never exported with a backup, and is never logged; Settings can make a
new one. Requests whose Host isn't this PC's loopback are refused (DNS rebinding),
and no CORS headers are sent, so a web page can't read anything back.

Every endpoint takes GET or POST and answers JSON:

    /api/status                  version, what's playing, the category showing
    /api/sounds                  [{id, name, hotkey, categories, playing}]
    /api/categories              ["Memes", ...]
    /api/play?id=… or ?name=…    play a pad (name: exact, any case)
    /api/stop?id=… or ?name=…    stop one sound;  /api/stop alone stops everything
    /api/pause                   pause everything / resume
    /api/random[?category=…]     a random sound (default: the category showing;
                                 category= with nothing after it: any sound)

The HTTP side runs on its own thread; each request is handed to the UI thread
(`RemoteControl.request`) and answered from there, so it never touches the
window's state from another thread.
"""
from __future__ import annotations

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
ACTIONS = ("status", "sounds", "categories", "play", "stop", "pause", "random")


def new_token() -> str:
    return secrets.token_urlsafe(24)


@dataclass
class Job:
    action: str
    params: dict
    done: threading.Event = field(default_factory=threading.Event)
    status: int = 500
    body: object = None


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
                return self._answer(503, {"error": "the app is busy, try again"})
            self._answer(job.status, job.body)

        do_GET = do_POST = _go

    return Handler


# --------------------------------------------------------------------------- the app side

def dispatch(mw: MainWindow, action: str, params: dict) -> tuple[int, object]:
    """Carry out one request on the window (UI thread)."""
    cfg = mw.cfg
    playing = mw.engine.playing()
    if action == "status":
        from soundboard import __version__
        return 200, {"version": __version__, "category": cfg.category,
                     "playing": [s for s in playing if s in mw.pads]}
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
        if cat and cat not in cfg.categories:
            return 404, {"error": f"no category called {cat!r}"}
        sid = mw.play_random(cat)
        if sid is None:
            return 404, {"error": "no sound to play there"}
        return 200, {"playing": sid, "name": mw.meta(sid).name}
    # play / stop: one sound, by id or name
    if action == "stop" and not ("id" in params or "name" in params):
        mw.stop_all()
        return 200, {"stopped": "all"}
    m = find_sound(mw, params)
    if m is None:
        return 404 if params else 400, {"error": "no such sound" if params
                                         else "say which: ?id=… or ?name=…"}
    if action == "stop":
        mw.engine.stop(m.id)
        return 200, {"stopped": m.id}
    if m.id not in mw.audio:
        return 409, {"error": "that sound hasn't loaded (yet)"}
    mw.play(m.id)
    return 200, {"playing": m.id, "name": m.name}


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
