"""A failed mic effect set-up sends its log by itself: what soundboard/mic/micdiag.py wrote
during the step, what the effect logged, and a fresh look at the PC, to the same server as
the sound store (SECURITY.md lists it). Mics' names and device details go with it; the
user's name, home folder and PC name are taken out first.

Only the installed app, only with the anonymous count's switch on and outside Offline mode
(usage.enabled, usage._off): none of our own runs ever send one. At most MAX_SENDS a launch;
the server keeps to a few a day from one address. Call send() from the UI thread: all the
reading and sending happens on its own thread, and a failure to send is only a log line."""
from __future__ import annotations

import logging
import os
import re
import threading
import time
import urllib.request

from soundboard import __version__
from soundboard.core import usage
from soundboard.online import net

log = logging.getLogger(__name__)

URL = "https://onion-board-store.onion-alien.workers.dev/v1/miclog"   # (store.BASE's server)
MAX_BYTES = 60 * 1024   # the server takes 64 kB
MAX_SENDS = 3           # a launch: someone trying again and again says nothing new
FRESH_S = 15 * 60       # the admin step's report this recent is about this failure
STEP_KB = 32            # how much of each part goes, from its end
EFFECT_KB = 8
ADMIN_KB = 6
LOOK_KB = 12
_KIND = re.compile(r"[A-Za-z0-9._-]{1,40}")

_sends = 0


def scrub(text: str, env=None) -> str:
    """`text` without who this is: the home folder, user name, PC name and any e-mail
    address. Mics' and devices' names stay."""
    env = os.environ if env is None else env
    text = re.sub(r"(?i)\b[A-Z]:\\Users\\[^\\\s|,)'\"]+", r"%USERPROFILE%", text)
    for name, instead in (("USERPROFILE", "%USERPROFILE%"), ("USERNAME", "<user>"),
                          ("COMPUTERNAME", "<pc>"), ("USERDOMAIN", "<pc>")):
        value = env.get(name, "")
        if len(value) >= 2:
            text = re.sub(rf"(?i)(?<![A-Za-z0-9]){re.escape(value)}(?![A-Za-z0-9])", instead, text)
    return re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "<e-mail>", text)


def _tail(path, kb: int) -> str:
    try:
        with open(path, "rb") as f:
            size = f.seek(0, os.SEEK_END)
            f.seek(max(0, size - kb * 1024))
            return f.read().decode("utf-8", "replace")
    except OSError as e:
        return f"(can't read it: {type(e).__name__})"


def build(kind: str, mic: str, guid: str | None = None) -> str:
    """The whole log for one failure, the verdicts on top."""
    from soundboard.mic import directmic, micdiag
    step = micdiag.report_path()
    try:
        age = time.time() - step.stat().st_mtime
    except OSError:
        age = None
    fresh = age is not None and age < FRESH_S
    stale = "none at all" if age is None else f"{age:.0f} s old"
    parts = [("the admin step", _tail(step, STEP_KB) if fresh else
              f"(no report from this step: {stale})")]
    parts.append(("the effect's log", _tail(directmic.data_dir() / micdiag.APO_LOG, EFFECT_KB)))
    if not fresh:
        logs = directmic.admin_logs()
        parts.append(("the newest admin log", _tail(logs[0], ADMIN_KB)))
    try:
        look = "\n".join(micdiag.snapshot(guid or directmic.endpoint_for(mic)))
    except Exception as e:  # noqa: BLE001 - what's above still goes
        look = f"(the look failed: {type(e).__name__}: {e})"
    parts.append(("a look now", look[-LOOK_KB * 1024:]))
    verdicts = [m.group(0) for _name, text in parts
                for m in re.finditer(r"^.*verdict: .*$", text, re.M)]
    head = [f"Onion Board {__version__}, mic set-up failed: {kind}", f"mic picked: {mic}",
            *verdicts]
    body = "\n".join(head) + "".join(f"\n\n##### {name}\n{text}" for name, text in parts)
    return scrub(body).encode("utf-8", "replace")[:MAX_BYTES].decode("utf-8", "ignore")


def _post(kind: str, body: str, timeout: float = 20) -> bool:
    req = urllib.request.Request(URL, data=body.encode("utf-8"), method="POST", headers={
        "User-Agent": "OnionBoard (mic log)", "Content-Type": "text/plain; charset=utf-8",
        "X-Onion-Version": __version__, "X-Onion-Kind": kind})
    try:
        with net.urlopen(req, timeout=timeout, feature=usage.FEATURE) as r:
            return 200 <= r.status < 300
    except Exception as e:  # noqa: BLE001 - offline, switched off meanwhile, server down
        log.info("the mic log wasn't sent: %s", e)
        return False


def allowed(cfg) -> bool:
    """The anonymous count's own gate: the installed app, its switch on, not Offline."""
    return usage.enabled() and not usage._off(cfg)


def send(cfg, kind: str, mic: str | None) -> bool:
    """Send the log of this failure, on its own thread. Whether one is on its way."""
    global _sends
    if not allowed(cfg) or _sends >= MAX_SENDS:
        return False
    _sends += 1
    kind = kind if _KIND.fullmatch(kind or "") else "other"
    mic = mic or ""

    def run():
        try:
            if _post(kind, build(kind, mic)):
                log.info("the mic log was sent (%s)", kind)
        except Exception:  # noqa: BLE001 - only a log: the app goes on
            log.warning("couldn't send the mic log", exc_info=True)
    threading.Thread(target=run, name="mic-log", daemon=True).start()
    return True
