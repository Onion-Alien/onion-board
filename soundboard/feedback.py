"""Where "Join the Discord", "Send feedback" and "Report a problem" go.

All three only open a page in the user's browser: nothing is sent by the app, and the
user decides what to type and whether to submit. The feedback form needs no
account (a GitHub issue does), and gets the app's version in the address so a
report says which version it's about."""
from __future__ import annotations

from urllib.parse import quote, urlencode

from soundboard.updates import REPO

# the Onion Board Discord server: chat, help, and new versions (a permanent invite)
DISCORD_URL = "https://discord.gg/FhKGaWCWHM"
# the no-account feedback form; empty = fall back to GitHub issues
FORM_URL = "https://tally.so/r/rjxjyM"
ISSUE_URL = f"https://github.com/{REPO}/issues/new"


def feedback_url(version: str, improve=()) -> str:
    """The form, with the version and the "What would you improve?" picks (the feedback
    box, ui/feedbackdialog.py) as its hidden fields."""
    if FORM_URL:
        q = {"version": version, **({"improve": ",".join(improve)} if improve else {})}
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
