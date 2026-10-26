"""The usage count's words: the fixed tags and rough buckets a count is sent as
(usage.py), made from a typed answer, a link, a number or this PC's system. Pure
functions: nothing here sends anything."""
from __future__ import annotations

import hashlib
import re
import sys
import urllib.parse

# the installer's "Where did you hear about Onion Board?" picks; Other's typed answer
# goes through heard_tag() too, and anything else is sent as "other-<words>" or not at all
HEARD = ("youtube", "reddit", "github", "google", "friend")
HEARD_ALIASES = {"yt": "youtube", "you tube": "youtube", "youtube.com": "youtube",
                 "reddit.com": "reddit", "github.com": "github", "a friend": "friend",
                 "friends": "friend", "google.com": "google", "x": "twitter",
                 "twitter.com": "twitter", "tiktok.com": "tiktok", "tik tok": "tiktok"}
HEARD_MAX = 24   # characters of a typed answer, after tidying
# the sites a downloaded sound is counted under (download_site); anything else is "other"
DL_SITES = ("youtube", "tiktok", "soundcloud", "instagram", "x", "reddit", "twitch",
            "myinstants", "other")
_DL_HOSTS = (("youtube", ("youtube.com", "youtu.be", "youtube-nocookie.com")),
             ("tiktok", ("tiktok.com",)), ("soundcloud", ("soundcloud.com", "snd.sc")),
             ("instagram", ("instagram.com",)), ("x", ("x.com", "twitter.com")),
             ("reddit", ("reddit.com", "redd.it")), ("twitch", ("twitch.tv",)),
             ("myinstants", ("myinstants.com",)))
OTHER_MAX = 100   # characters of what was typed under Other, as dashed words


def user_tag(sid: str) -> str:
    """A short tag made from the random ID, sent as each count's "ref". GoatCounter
    swaps "session" for its own number that starts over after 8 hours, so the daily
    counts of one person only link up across days through this. A hash, so the ID
    itself isn't what's kept there."""
    return "u-" + hashlib.sha256(sid.encode()).hexdigest()[:12]


def _wordlike(w: str) -> bool:
    """A word, a short name ("tv") or a number: not keyboard mashing ("asdfgh")."""
    return w.isdigit() or ((len(w) <= 3 or bool(re.search(r"[aeiouy]", w)))
                           and not re.search(r"[^aeiouy\d]{5}", w))


def heard_tag(text: str) -> str:
    """The installer's answer as a short tag for the first-start event: one of HEARD,
    "other-<a-few-words>" for a typed answer that reads like a name (a site, an app,
    "discord server"), or "" for none. Typed text that doesn't look like that is
    dropped, not sent: an email address, a link with a path, a number (a phone),
    symbols, keyboard mashing or more than three words."""
    t = " ".join(str(text or "").lower().split())
    t = HEARD_ALIASES.get(t, t)
    if t in HEARD:
        return t
    if (not t or len(t) > HEARD_MAX or "@" in t or "/" in t
            or not re.fullmatch(r"[a-z0-9 .\-]+", t) or re.search(r"\d{3}", t)):
        return ""
    words = re.findall(r"[a-z0-9]+", t.replace(".com", ""))
    if not 1 <= len(words) <= 3 or not all(_wordlike(w) for w in words):
        return ""
    for w in words:   # "a youtube video", "my friend", "google search"
        w = HEARD_ALIASES.get(w, w)
        if w in HEARD:
            return w
    return "other-" + "-".join(words)


def bucket(n: int) -> str:
    """A count as a rough bucket: 0, 1-10, 11-50, 51-plus."""
    return "0" if n <= 0 else "1-10" if n <= 10 else "11-50" if n <= 50 else "51-plus"


def age_bucket(days: float) -> str:
    """How long ago it was installed, roughly."""
    return ("day-1" if days < 1 else "days-2-7" if days < 7 else "days-8-30" if days < 30
            else "days-31-plus")


def open_bucket(seconds: float) -> str:
    """How long it was open, roughly."""
    h = seconds / 3600
    return ("under-15m" if h < 0.25 else "15m-1h" if h < 1 else "1-3h" if h < 3
            else "3-8h" if h < 8 else "8h-plus")


def download_site(url: str) -> str:
    """The site a link is on, as one of DL_SITES: the name only, never the link."""
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    for name, domains in _DL_HOSTS:
        if any(host == d or host.endswith("." + d) for d in domains):
            return name
    return "other"


def download_bucket(n: int) -> str:
    """How many sounds were fetched since the last daily count: 0, 1, 2-5, 6-20 or
    21-plus."""
    return ("0" if n <= 0 else "1" if n == 1 else "2-5" if n <= 5 else "6-20" if n <= 20
            else "21-plus")


def launch_bucket(n: int) -> str:
    """How many times it was started since the last daily count: 0 (left open since
    then), 1, 2-5 or 6-plus."""
    return "0" if n <= 0 else "1" if n == 1 else "2-5" if n <= 5 else "6-plus"


def os_tag() -> str:
    """Which system, nothing finer: win11, win10, win-older, linux or other."""
    if sys.platform == "win32":
        try:
            v = sys.getwindowsversion()
        except AttributeError:
            return "other"
        if v.major >= 10:
            return "win11" if v.build >= 22000 else "win10"
        return "win-older"
    return "linux" if sys.platform.startswith("linux") else "other"


def ach_tag(ach_id: str) -> str:
    """An achievement's id as a count's word: first_blood -> ach-first-blood."""
    return "ach-" + ach_id.replace("_", "-")


def ach_bucket(n: int) -> str:
    """How many achievements were earned, roughly."""
    return ("0" if n <= 0 else "1-2" if n <= 2 else "3-5" if n <= 5 else
            "6-10" if n <= 10 else "11-20" if n <= 20 else "21-plus")


def score_bucket(n: int) -> str:
    """The achievement score (achievements.score()), roughly."""
    return ("0" if n <= 0 else "1-50" if n <= 50 else "51-150" if n <= 150 else
            "151-400" if n <= 400 else "401-1000" if n <= 1000 else
            "1001-2000" if n <= 2000 else "2001-plus")


def theme_tag(name: str) -> str:
    """A built-in theme's name as a count's word ("Midnight Blue" -> midnight-blue);
    anything else (a newer version's) is "other"."""
    from soundboard.ui.kit import theme
    if name not in theme.THEMES:
        return "other"
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "other"


def other_tag(text: str, limit: int = OTHER_MAX) -> str:
    """What was typed under Other as dashed words ("more-anime-sounds"), any language.
    Anything that could say who someone is is dropped first: an email address, a link,
    a long number (a phone), an @name. At most `limit` characters, cut at a word."""
    words = []
    for w in str(text or "").lower().split():
        if ("@" in w or "/" in w or "www." in w or re.search(r"\.[a-z]{2,4}$", w)
                or re.search(r"\d{4,}", w)):
            continue
        words += [p for p in re.split(r"[\W_]+", w) if p]
    out = ""
    for w in words:
        if len(out) + len(w) + 1 > limit:
            break
        out = f"{out}-{w}" if out else w
    return out
