"""The control API's requests for the tabs: the Voice tab, the live speed / pitch / effects,
Who's listening, the Apps tab, My voice combos, the mic gate and the radio (`remote`
re-exports them)."""
from __future__ import annotations

import difflib
import random
from typing import TYPE_CHECKING

from soundboard.control import streamapi
from soundboard.control.remoteparams import BAD_ON, number, on_value, set_volume

if TYPE_CHECKING:
    from soundboard.ui.window.mainwindow import MainWindow


# --------------------------------------------------------------------------- the Voice tab

VOICE_ACTIONS = ("voice", "voices", "say")
SAY_MAX = 500           # characters in one ?text=


def voice_names(mw: MainWindow) -> list[str]:
    """The voices a request can pick: the built-in ones, then the saved ones ("My own
    mix" isn't one: picking it opens a window to make it)."""
    from soundboard import voicefx
    fx = _voice_tab(mw).fx
    return [n for n in (*voicefx.PRESETS, *(n for n in fx.store.voices
                                            if n not in voicefx.PRESETS))
            if fx.offered(n)]


def _voice_tab(mw: MainWindow):
    """The Voice tab, for a caller that checked mw.tabctl.tab_on("voice")."""
    from soundboard.ui.window.taboff import VoiceOff
    voice = mw.voice
    assert not isinstance(voice, VoiceOff)   # switched on: the real tab
    return voice


def voice_state(mw: MainWindow) -> dict:
    fx = _voice_tab(mw).fx
    return {"voice": fx.btn_power.isChecked(), "voice_name": fx.preset}


def dispatch_voice(mw: MainWindow, action: str, params: dict) -> tuple[int, object]:
    from soundboard import voicefx
    if not mw.tabctl.tab_on("voice"):
        return 409, VOICE_OFF
    fx = _voice_tab(mw).fx
    if action == "voices":
        saved = fx.store.voices
        return 200, {**voice_state(mw),
                     "voices": [{"name": n, "shown": voicefx.shown(n), "saved": n in saved}
                                for n in voice_names(mw)]}
    if action == "say":
        sp = _voice_tab(mw).speech
        if (params.get("stop") or "").strip() not in ("", "0"):
            sp.ctl.stop_speaking()
            return 200, {"stopped": True}
        text = " ".join((params.get("text") or "").split())
        if not text:
            return 400, {"error": "say what: ?text=…"}
        if len(text) > SAY_MAX:
            return 400, {"error": f"text= is too long: at most {SAY_MAX} characters"}
        sp.say_line(text)
        return 200, {"saying": text}
    seconds = None
    if "seconds" in params:
        seconds = number(params, "seconds", 0, streamapi.VOICE_S_MAX)
        if seconds is None:
            return 400, {"error": f"seconds= takes a number, 0 to {streamapi.VOICE_S_MAX}"}
    if (params.get("random") or "").strip() not in ("", "0"):
        pool = fx._roll_pool()
        if not pool:
            return 404, {"error": "no other voice to pick"}
        name = random.choice(pool)
        if seconds:
            return 200, streamapi.voice_for(mw, name, seconds)
        fx.pick(name)
        return 200, voice_state(mw)
    if "name" in params:   # voice?name=Robot
        want = params["name"].strip().casefold()
        names = voice_names(mw)
        match = next((n for n in names
                      if want in (n.casefold(), voicefx.shown(n).casefold())), None)
        if match is None:
            body = {"error": f"no voice called {params['name']!r}", "voices": names}
            close = difflib.get_close_matches(params["name"].strip(), names, 3, 0.5)
            if close:
                body["did_you_mean"] = close
            return 404, body
        if seconds:
            return 200, streamapi.voice_for(mw, match, seconds)
        fx.pick(match)
        return 200, voice_state(mw)
    on = on_value(params, fx.btn_power.isChecked())
    if on is None:
        return 400, BAD_ON
    mw.hkctl._set_voice(on)
    return 200, voice_state(mw)


# --------------------------------------------------------------------------- live controls
# The speed / pitch / effects popup on the Sounds tab's transport bar
# (ui/speedpitch.SpeedPitchButton). Requests go through the popup itself, so the PC's
# sliders always show what's playing.

LIVE_ACTIONS = ("speed", "pitch", "effects", "reset")


def live_state(mw: MainWindow) -> dict:
    from soundboard.audio import livefx
    b = mw.speed_btn
    speed, pitch, keep = b.values()
    fx = b.fx_values()
    preset = next((n for n in livefx.PRESETS if b.preset_on(n)), "")
    return {"speed": round(speed, 3), "pitch": round(pitch, 2), "keep_pitch": keep,
            "effects": {k: round(v, 3) for k, v in fx.items()}, "preset": preset}


def dispatch_live(mw: MainWindow, action: str, params: dict) -> tuple[int, object]:
    from soundboard.audio import livefx
    from soundboard.ui.sounds import speedpitch as sp
    b = mw.speed_btn
    speed, pitch, keep = b.values()
    if action == "reset":
        b.reset()
        return 200, live_state(mw)
    if action == "effects":
        if (params.get("reset") or "").strip() not in ("", "0"):
            b.set_fx({})
            return 200, live_state(mw)
        if "preset" in params:
            name = params["preset"].strip().lower()
            match = next((n for n in livefx.PRESETS if n.lower() == name), None)
            if match is None and name not in ("", "none", "off"):
                return 404, {"error": f"no preset called {params['preset']!r}",
                             "presets": list(livefx.PRESETS)}
            if match:
                b.apply_preset(match)
            else:
                b.set_fx({})
            return 200, live_state(mw)
        knobs = {q.key: q for q in livefx.PARAMS}
        given = [k for k in params if k in knobs]
        if not given:   # what there is to set
            return 200, {**live_state(mw), "presets": list(livefx.PRESETS),
                         "knobs": [{"key": q.key, "label": q.label, "lo": q.lo, "hi": q.hi,
                                    "unit": q.unit.strip()} for q in livefx.PARAMS]}
        amounts = b.fx_values()
        for k in given:
            v = number(params, k, knobs[k].lo, knobs[k].hi)
            if v is None:
                return 400, {"error": f"{k}= takes a number, {knobs[k].lo:g} to "
                                      f"{knobs[k].hi:g}"}
            amounts[k] = v
        b.set_fx(amounts)
        return 200, live_state(mw)
    # speed / pitch
    if "keep" in params:
        k = on_value({"on": params["keep"]}, keep)
        if k is None:
            return 400, {"error": "keep= takes 1, 0 or toggle"}
        keep = k
    step = (params.get("step") or "").strip().lower()
    q, now = (sp.SPEED, speed) if action == "speed" else (sp.PITCH, pitch)
    if "set" in params:
        v = number(params, "set", q.lo, q.hi)
        if v is None:
            return 400, {"error": f"set= takes a number, {q.lo:g} to {q.hi:g}"}
    elif step in ("up", "down", "+", "-"):
        up = step in ("up", "+")
        if action == "speed":   # the next quick speed (0.5, 0.75, 1, 1.25, 1.5, 2)
            ladder = [s for s in sp.QUICK if (s > now + 1e-6 if up else s < now - 1e-6)]
            v = (min(ladder) if up else max(ladder)) if ladder else now
        else:
            v = round(now) + (1 if up else -1)
        if q.lo <= now <= q.hi:          # a Redline value set on the PC stays as it is
            v = min(max(v, q.lo), q.hi)
    elif "keep" in params:
        v = now
    else:
        return 400, {"error": f"say how: ?set={q.lo:g} to {q.hi:g} or ?step=up / down"}
    if action == "speed":
        speed = v
    else:
        pitch = v
    b.set_values(speed, pitch, keep)
    return 200, live_state(mw)


# --------------------------------------------------------------------------- who's listening

def mode_state(mw: MainWindow, full: bool = True) -> dict:
    from soundboard.mic import destination, profiles
    d = mw.cfg.dest if isinstance(mw.cfg.dest, dict) else {}
    now = destination.resolve(d)
    p = profiles.current(d)
    out: dict[str, object] = {"mode": now.key, "mode_label": now.label, "simple": p.key,
           "simple_label": p.label,
           "explain": profiles.explain(d, getattr(mw, "mode_why", ""), english=True)}
    if full:
        out["modes"] = [{"key": m.key, "label": m.label, "note": m.note}
                        for m in destination.all_modes(d.get("custom"))]
        out["simples"] = [{"key": q.key, "label": q.label, "summary": q.summary,
                           "details": q.details} for q in profiles.PROFILES]
    return out


def dispatch_mode(mw: MainWindow, params: dict) -> tuple[int, object]:
    """?simple= picks a simple mode (Game, Voice chat, Clean, Advanced); ?set= one exact
    destination mode, which is Advanced (or Clean, for Off). Both apply and save, and
    the Sounds tab's dropdown and the Setup tab's picker show it."""
    from soundboard.mic import destination, profiles
    from soundboard.ui.setup import destpanel
    if "simple" in params:
        want = params["simple"].strip().lower()
        p = next((q for q in profiles.PROFILES if want in (q.key, q.label.lower())), None)
        if p is None:
            return 404, {"error": f"no sound mode called {params['simple']!r}",
                         **mode_state(mw)}
        destpanel.set_simple(mw, p.key)
    elif "set" in params:
        d = mw.cfg.dest if isinstance(mw.cfg.dest, dict) else {}
        want = params["set"].strip().lower()
        match = next((m for m in destination.all_modes(d.get("custom"))
                      if want in (m.key.lower(), m.label.lower())), None)
        if match is None:
            return 404, {"error": f"no mode called {params['set']!r}", **mode_state(mw)}
        destpanel.set_exact(mw, match.key)
    return 200, mode_state(mw)


# --------------------------------------------------------------------------- the Apps tab

APP_ACTIONS = ("apps", "app")
APPS_OFF = {"error": "the Apps tab is switched off in Onion Board's Settings > Tabs"}


def _apps_tab(mw: MainWindow):
    from soundboard.ui.apps.appspanel import AppsTab
    a = getattr(mw, "apps", None)
    return a if isinstance(a, AppsTab) else None


def app_dict(row) -> dict:
    return {"name": row.name.text(), "exe": row.exe, "running": row.app is not None,
            "sending": row.sending, "volume": row.vol.spin.value()}


def dispatch_apps(mw: MainWindow, action: str, params: dict) -> tuple[int, object]:
    """The Apps tab's Send switch and volume, through the cards themselves, so the PC
    shows what a request did."""
    tab = _apps_tab(mw)
    if tab is None:
        return 409, APPS_OFF
    rows = list(tab.rows.values())
    if action == "apps":
        return 200, [app_dict(r) for r in rows]
    asked = (params.get("name") or params.get("exe") or "").strip()
    want = asked.casefold()
    if not want:
        return 400, {"error": "say which: ?name=… (/api/apps lists them)"}
    row = next((r for r in rows
                if want in (r.exe.casefold(), r.exe.casefold().removesuffix(".exe"),
                            r.name.text().strip().casefold())), None)
    if row is None:
        return 404, {"error": f"no program called {asked!r} on the Apps tab",
                     "apps": [r.exe for r in rows]}
    if "volume" in params:
        err = set_volume(row.vol.spin, {"set": params["volume"]})
        if err:
            return err
    if "send" in params:
        on = on_value({"on": params["send"]}, row.sending)
        if on is None:
            return 400, {"error": "send= takes 1, 0 or toggle"}
        if on and row.app is None:
            return 409, {"error": "that program isn't running", **app_dict(row)}
        if on != row.sending:
            row.btn_send.setChecked(on)   # -> AppsTab._on_send
    return 200, app_dict(row)


SETUP_TABS = ("sounds", "radio", "apps")


def setups_state(mw: MainWindow) -> dict:
    ls = mw.livesetups
    return {"setups": list(ls.setups()),
            "on": {t: ls.names.get(t, "") for t in SETUP_TABS if ls.button(t) is not None}}


def dispatch_setups(mw: MainWindow, action: str, params: dict) -> tuple[int, object]:
    """My voice combos on a live control, as its chips pick them (without the question an AI
    voice or a language asks first: a button can't answer it)."""
    ls = mw.livesetups
    if action == "setups":
        return 200, setups_state(mw)
    tab = (params.get("tab") or "sounds").strip().lower()
    if tab not in SETUP_TABS:
        return 400, {"error": "tab= takes sounds, radio or apps"}
    if ls.button(tab) is None:
        return 409, RADIO_OFF if tab == "radio" else APPS_OFF
    if "name" not in params:
        return 400, {"error": "say which: ?name=… (/api/setups lists them)"}
    want = params["name"].strip().casefold()
    names = list(ls.setups())
    match = next((n for n in names if n.casefold() == want), None)
    if want and match is None:
        body = {"error": f"no setup called {params['name']!r}", "setups": names}
        close = difflib.get_close_matches(params["name"].strip(), names, 3, 0.5)
        if close:
            body["did_you_mean"] = close
        return 404, body
    ls.pick(tab, match or "", ask=False)
    return 200, setups_state(mw)


def set_mic_gate(mw: MainWindow, on: bool):
    """Mute my mic while a sound plays: saved, on the engine, and the Who's listening
    boxes showing it."""
    from soundboard.ui.setup import destpanel
    mw.cfg.mic_gate = on
    destpanel.apply_send(mw.cfg, mw.engine)
    for panel in mw.findChildren(destpanel.DestPanel):
        panel.chk_gate.blockSignals(True)
        panel.chk_gate.setChecked(on)
        panel.chk_gate.blockSignals(False)
    mw._save_later()


# --------------------------------------------------------------------------- the radio
# The Radio tab (ui/radiopanel.RadioTab) does the work, so the PC shows what was picked.
# With Radio switched off in Settings > Privacy & security there's no radio at all.

RADIO_ACTIONS = ("stations", "radio", "radio_random", "radio_star", "radio_live",
                 "radio_hear", "radio_volume")
STATIONS_MAX = 100      # stations in one answer
RADIO_LISTS = ("popular", "favorites", "favourites", "recent")
RADIO_OFF = {"error": "the radio is switched off in Onion Board's Settings (Privacy & "
                      "security, or Tabs)"}
VOICE_OFF = {"error": "the Voice tab is switched off in Onion Board's Settings > Tabs"}


def _radio_tab(mw: MainWindow):
    from soundboard.ui.radio.radiopanel import RadioTab
    r = getattr(mw, "radio", None)
    return r if isinstance(r, RadioTab) else None


def station_dict(r, s) -> dict:
    now = r.player.station
    return {"id": s.uuid, "name": s.name, "country": s.country, "tags": list(s.tags[:3]),
            "bitrate": s.bitrate, "fav": s.uuid in r._fav_ids,
            "playing": now is not None and now.uuid == s.uuid}


def radio_state(mw: MainWindow) -> dict:
    r = _radio_tab(mw)
    if r is None:
        return {"available": False}
    st = r.player.station
    return {"available": True, "on": st is not None,
            "connecting": st is not None and r.player.status == "connecting",
            "station": station_dict(r, st) if st is not None else None,
            "title": r._title if st is not None else "",
            "live": bool(mw.engine.radio_live), "hear": r.chk_hear.isChecked(),
            "volume": r.vol.spin.value(), "last": bool(r.cfg.radio.get("last"))}


def dispatch_radio(mw: MainWindow, action: str, params: dict) -> tuple[int, object]:
    r = _radio_tab(mw)
    if r is None:
        return 409, RADIO_OFF
    if action == "stations":
        which = (params.get("list") or "popular").strip().lower()
        if which not in RADIO_LISTS + ("search",):
            return 400, {"error": "list= takes popular, favorites, recent or search"}
        stations, loading, error = r.phone_list(which, params.get("q") or "")
        return 200, {"list": which, "loading": loading, "error": error,
                     "stations": [station_dict(r, s) for s in stations[:STATIONS_MAX]]}
    if action == "radio":
        if params.get("id"):
            s = r._stations.get(params["id"])
            if s is None:
                return 404, {"error": "no such station (list them with /api/stations)"}
            r.play(s)
        elif "on" in params or not params:
            on = on_value(params, r.is_active())
            if on is None:
                return 400, BAD_ON
            if on and not r.is_active():
                from soundboard.online.radio import Station
                s = Station.from_saved(r.cfg.radio.get("last") or {})
                if s is None:
                    return 404, {"error": "no station has played yet: pick one"}
                r.play(r._stations.setdefault(s.uuid, s))
            elif not on:
                r.stop()
        else:
            return 400, {"error": "say which: ?id=… or ?on=1 / 0 / toggle"}
        return 200, radio_state(mw)
    if action == "radio_random":
        which = (params.get("list") or "").strip().lower()
        if not which:
            r.start()
            r.play_random()
            if not r.is_active():
                return 404, {"error": "no station to pick from yet"}
            return 200, radio_state(mw)
        if which not in RADIO_LISTS:
            return 400, {"error": "list= takes popular, favorites or recent"}
        now = r.player.station
        pool = [s for s in r.phone_list(which, "")[0] if now is None or s.uuid != now.uuid]
        if not pool:
            return 404, {"error": "no station to pick from there"}
        r.play(random.choice(pool))
        return 200, radio_state(mw)
    if action == "radio_star":
        s = r._stations.get(params["id"]) if params.get("id") else r.player.station
        if s is None:
            return 404, {"error": "no such station" if params.get("id") else
                         "nothing is playing: say which with ?id=…"}
        on = on_value(params, s.uuid in r._fav_ids)
        if on is None:
            return 400, BAD_ON
        if on != (s.uuid in r._fav_ids):
            r._toggle_fav(s.uuid)
            r._update_buttons()
        return 200, {"id": s.uuid, "fav": s.uuid in r._fav_ids}
    if action == "radio_live":
        on = on_value(params, bool(mw.engine.radio_live))
        if on is None:
            return 400, BAD_ON
        r._on_live(on)
        return 200, radio_state(mw)
    if action == "radio_hear":
        on = on_value(params, r.chk_hear.isChecked())
        if on is None:
            return 400, BAD_ON
        r.chk_hear.setChecked(on)   # -> _on_hear
        return 200, radio_state(mw)
    err = set_volume(r.vol.spin, params)   # radio_volume -> _on_vol
    return err or (200, radio_state(mw))
