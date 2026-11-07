"""A usage event as one short readable line, so a test can say what was counted in a few
characters (`error/2.9.0/KeyError@soundboard/x.py:12`). Tests only: the wire has real fields,
which test_usage.py checks on their own."""
from __future__ import annotations

from soundboard import __version__
from soundboard.core.usagetags import bucket, os_tag


def _at(attrs: dict) -> str:
    return f"{attrs['file']}:{attrs['line']}" if attrs.get("file") else ""


def _chain(attrs: dict, inner: str) -> str:
    """`<deepest line><<its caller>~<library call>`."""
    out = _at(attrs)
    stack = attrs.get("stack") or []
    if len(stack) > 1:
        out += "<" + stack[-2].rsplit(":", 1)[0]
    if attrs.get(inner):
        out += "~" + attrs[inner]
    return out


def _daily(a: dict, version: str, os: str) -> list[str]:
    out = [f"/app/{version}", f"age/{a['age']}"]
    if a.get("route"):
        out.append(f"route/{a['route']}")
    out += [f"sounds/{a['sounds']}", f"played/{a['played']}", f"open/{a['open']}",
            f"downloads/{a['downloads']}", f"lang/{a['lang']}/{a['lang_source']}",
            f"lang-windows/{a['lang_windows']}", f"theme/{a['theme']}", f"os/{os}",
            f"launches/{a['launches']}", f"achievements/{a['achievements']}",
            f"ach-score/{a['ach_score']}"]
    return out


def _freeze(a: dict, ver: str) -> str:
    chain = _chain(a, "stuck_in")
    out = f"freeze/{ver}" + (f"@{chain}" if chain else "")
    rest = [word for key, word in (("in_dialog", "in-dialog"), ("all_held", "all-held"),
                                   ("gc_sweep", "gc-sweep"), ("no_cpu", "no-cpu")) if a.get(key)]
    if a.get("lasted"):
        rest.append("lasted-" + a["lasted"] if a["lasted"] != "never-ended" else "never-ended")
    if a.get("busy"):
        rest.append(a["busy"] if a["busy"] == "idle" else "busy-" + a["busy"]
                    + (f"@{a['busy_at']}" if a.get("busy_at") else ""))
    if a.get("memory"):
        rest.append(f"mem-{a['memory']}")
    if a.get("paging"):
        rest.append("paging")
    return out + "".join(f"/{p}" for p in rest)


def names(e: dict, version: str = __version__, os: str = "") -> list[str]:
    """Event `e` as its lines (the daily event says many)."""
    n, a = e["name"], e.get("attrs") or {}
    ver = a.get("version", version)
    if n == "daily":
        return _daily(a, version, os or os_tag())
    if n in ("feature.used", "feature.on"):
        return [f"used/{a['feature']}"]
    if n == "problems_dropped":
        return [f"problems-dropped/{bucket(e.get('count', 1))}"]
    line = {
        "older": lambda: a["raw"],
        "tab.opened": lambda: f"tab/{a['tab']}",
        "first_start": lambda: "first-start" + (f"/heard-{a['heard']}" if a.get("heard") else ""),
        "step": lambda: f"step/{a['step']}",
        "opt_out": lambda: f"opt-out/{a['where']}",
        "uninstall": lambda: f"uninstall/{version}",
        "update_now": lambda: f"update-now/{version}-to-{a['to']}",
        "updated": lambda: f"updated/{a['from']}-to-{version}",
        "twitch_channel": lambda: f"twitch-channel/{a['login']}",
        "freeze": lambda: _freeze(a, ver),
        "unclean_exit": lambda: "/".join(
            p for p in ("unclean-exit", ver, a.get("why"), a.get("detail")) if p),
        "startup_failed": lambda: "/".join(
            p for p in ("startup-failed", ver, a.get("detail")) if p),
        "failed": lambda: "/".join(("failed", ver, a["what"], *a["detail"])),
        "warned": lambda: f"warned/{ver}/" + "@".join(p for p in (a.get("type"), _at(a)) if p),
        "improve": lambda: _improve(a),
    }.get(n)
    if line:
        return [line()] * e.get("count", 1)
    # crash, error
    chain = _chain(a, "raised_in")
    tag = (a.get("type") or "") + (chain if chain.startswith("~") or not a.get("type")
                                   else f"@{chain}" if chain else "")
    return [f"{n}/{ver}" + (f"/{tag}" if tag else "")] * e.get("count", 1)


def _improve(a: dict) -> str:
    if a.get("said"):
        return f"improve/{a['pick']}/" + ("said/" if a["pick"] == "bugs" else "") + a["said"]
    return f"improve/{a['pick']}" + (f"/{a['more']}" if a.get("more") else "")


def name(e: dict | None) -> str:
    """One event as its one line; "" for none."""
    return names(e)[0] if e else ""
