"""Where "Join the Discord", "Send feedback" and "Report a problem" go.

All three only open a page in the user's browser: nothing is sent by the app, and the
user decides what to type and whether to submit. The feedback form needs no
account (a GitHub issue does), and gets the app's version in the address so a
report says which version it's about."""
from __future__ import annotations

import re
import sys
from urllib.parse import quote, urlencode

from soundboard.core.updates import REPO

# the Onion Board Discord server: chat, help, and new versions (a permanent invite)
DISCORD_URL = "https://discord.gg/FhKGaWCWHM"
# the no-account feedback form; empty = fall back to GitHub issues
FORM_URL = "https://tally.so/r/rjxjyM"
ISSUE_URL = f"https://github.com/{REPO}/issues/new"


def feedback_url(version: str, improve=()) -> str:
    """The form, with the version and the "What would you improve?" picks (the feedback
    box, ui/kit/feedbackdialog.py) as its hidden fields."""
    if FORM_URL:
        q = {"version": version, **({"improve": ",".join(improve)} if improve else {})}
        return f"{FORM_URL}?{urlencode(q)}"
    return problem_url(version)


def windows_version() -> str:
    """Windows' version and build, "10-19045" / "11-26100" (11 from build 22000), for a
    report's form ("" off Windows)."""
    try:
        build = sys.getwindowsversion().build
    except AttributeError:
        return ""
    return f"{11 if build >= 22000 else 10}-{build}"


def mic_error(prefix: str, text: str) -> str:
    """A short code for what failed ("mic-open-80070005"): `prefix` and the error
    numbers in an audio error's text (PortAudio's, then Windows'), never the text
    itself (it can hold a device name or a path)."""
    nums = re.findall(r"(?:PaErrorCode|error) (-?\d+)", text or "")
    parts = [f"{int(n) & 0xFFFFFFFF:08X}" if abs(int(n)) > 0xFFFF else n.lstrip("-")
             for n in nums]
    return "-".join([prefix, *parts])[:60]


def micfail_url(version: str, *, mic: str, mode: str, err: str) -> str:
    """The form for "the mic didn't work" (ui/kit/failreport.py), filled with what the
    report needs (the same names as the uninstaller's form): Windows' version, the
    mic's name, direct / cable and a short error code."""
    q = {"version": version, "from": "micfail", "win": windows_version(), "mic": mic,
         "mode": mode, "mictest": "fail", "err": err[:60]}
    if FORM_URL:
        return f"{FORM_URL}?{urlencode(q)}"
    return problem_url(version)


def problem_url(version: str, addon: str = "") -> str:
    """A new bug report; `addon` ("Onion Pocket 0.2.2") when it's about an add-on:
    it goes in the title and under the app's version."""
    body = (f"**Onion Board version:** {version}\n"
            + (f"**Add-on:** {addon}\n" if addon else "")
            + "\n**What happened?**\n\n\n"
            "**What did you expect?**\n\n")
    name, _, ver = addon.rpartition(" ")
    name = name if ver[:1].isdigit() else addon     # "Onion Pocket", not its version
    title = f"&title={quote(name + ': ')}" if addon else ""
    return f"{ISSUE_URL}?labels=bug{title}&body={quote(body)}"
