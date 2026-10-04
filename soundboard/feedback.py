"""Where "Send feedback" and "Report a problem" go.

Both only open a page in the user's browser: nothing is sent by the app, and the
user decides what to type and whether to submit. The feedback form needs no
account (a GitHub issue does), and gets the app's version in the address so a
report says which version it's about."""
from __future__ import annotations

from urllib.parse import quote, urlencode

from soundboard.updates import REPO

# the no-account feedback form; empty = fall back to GitHub issues
FORM_URL = "https://tally.so/r/rjxjyM"
ISSUE_URL = f"https://github.com/{REPO}/issues/new"


def feedback_url(version: str) -> str:
    if FORM_URL:
        return f"{FORM_URL}?{urlencode({'version': version})}"
    return problem_url(version)


def problem_url(version: str) -> str:
    body = (f"**Onion Board version:** {version}\n\n"
            "**What happened?**\n\n\n"
            "**What did you expect?**\n\n")
    return f"{ISSUE_URL}?labels=bug&body={quote(body)}"
