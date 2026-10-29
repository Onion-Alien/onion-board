"""The control API's app side: `dispatch` carries out one request on the window (UI
thread), the sounds, the play queue and the key pictures here, the tabs in `remotetabs`
(`remote` re-exports them)."""
from __future__ import annotations

import base64
from typing import TYPE_CHECKING

from soundboard.control import streamapi
from soundboard.control.remoteparams import (BAD_ON, find_category, find_sound, no_sound,
                                             on_value, set_volume)
from soundboard.control.remotetabs import (APP_ACTIONS, LIVE_ACTIONS, RADIO_ACTIONS,
                                           VOICE_ACTIONS, dispatch_apps, dispatch_live,
                                           dispatch_mode, dispatch_radio, dispatch_setups,
                                           dispatch_voice, live_state, mode_state,
                                           radio_state, set_mic_gate)

if TYPE_CHECKING:
    from soundboard.ui.window.mainwindow import MainWindow


# An Onion Watch alarm rings its pad as the voice "<sound id>:ring:<trigger>"
# (soundboard.ui.triggers.triggershost.RING): a phone or Stream Deck sees it as the pad playing.
RING = ":ring:"


def pad_of(voice: str) -> str:
    """The sound a playing voice is: an alarm's ring is its pad's."""
    return voice.split(RING, 1)[0]


def dispatch(mw: MainWindow, action: str, params: dict) -> tuple[int, object]:
    """Carry out one request on the window (UI thread)."""
    cfg = mw.cfg
    playing = mw.engine.playing()
    sounding = list(dict.fromkeys(pad_of(v) for v in playing))
    if action == "help":
        from soundboard.control.remote import ENDPOINTS
        return 200, {"endpoints": {f"/api/{a}": d for a, d in ENDPOINTS.items()},
                     "key": "send it as ?token=…, an X-Token header or Authorization: "
                            "Bearer …"}
    if action == "status":
        from soundboard import __version__
        from soundboard.control import keyimage
        return 200, {"version": __version__, "category": cfg.category,
                     "playing": [s for s in sounding if s in mw.pads],
                     "paused": bool(playing) and all(p for _, p in playing.values()),
                     "live": bool(mw.engine.sending),
                     "voice": mw.voice.fx.btn_power.isChecked(),
                     "voice_name": getattr(mw.voice.fx, "preset", ""),
                     "mic": bool(cfg.mic_enabled),
                     "hear": bool(mw.engine.mic_check),
                     "hotkeys": bool(mw.hkctl.hotkeys_on),
                     "keys": keyimage.controls_look(cfg.theme, cfg.language),
                     "mic_gate": bool(cfg.mic_gate),
                     **queue_state(mw),
                     "volume": mw.vol_sound.spin.value(),
                     **live_state(mw), **mode_state(mw, full=False),
                     "radio": radio_state(mw)}
    if action == "sounds":
        from soundboard.control import keyimage
        q = (params.get("q") or "").strip().casefold()
        cat = None
        if params.get("category"):
            cat = find_category(cfg, params["category"])
            if cat is None:
                return 404, {"error": f"no category called {params['category']!r}",
                             "categories": list(cfg.categories)}
        return 200, [{"id": m.id, "name": m.name, "hotkey": m.hotkey,
                      "categories": list(m.tags), "color": m.color,
                      "playing": m.id in sounding, "volume": round(m.volume * 100),
                      "loop": m.loop, "press": m.mode, "plays": m.plays,
                      "duration": round(m.duration, 2), "effects": bool(m.fx),
                      "look": keyimage.look(m, cfg.theme)}
                     for m in cfg.sounds
                     if (not q or q in m.name.casefold()) and (cat is None or cat in m.tags)]
    if action == "categories":
        return 200, list(cfg.categories)
    if action == "key_image":
        return key_image(mw, params, sounding)
    if action == "pause":
        paused = bool(playing) and all(p for _, p in playing.values())
        on = on_value(params, paused)
        if on is None:
            return 400, BAD_ON
        return 200, {"paused": mw.engine.pause_all(on)}
    if action == "random":
        cat = params.get("category")
        if cat:
            cat = find_category(cfg, cat)
            if cat is None:
                return 404, {"error": f"no category called {params['category']!r}",
                             "categories": list(cfg.categories)}
        sid = mw.playctl.play_random(cat)
        if sid is None:
            return 404, {"error": "no sound to play there"}
        m = mw.meta(sid)
        return 200, {"playing": sid, "name": m.name if m is not None else ""}
    if action == "last":
        sid = getattr(mw.playctl, "_last_sid", None)
        m = mw.meta(sid) if sid is not None else None
        if sid is None or m is None:
            return 404, {"error": "nothing has played yet"}
        if sid not in mw.audio:
            return 409, {"error": "that sound hasn't loaded (yet)"}
        mw.playctl.play(sid)
        return 200, {"playing": sid, "name": m.name}
    if action == "category":
        step = (params.get("step") or "").strip().lower()
        if step:
            if step not in ("next", "prev", "previous"):
                return 400, {"error": "step= takes next or prev"}
            mw.hkctl.step_category(1 if step == "next" else -1)
        elif "name" in params:
            name = params["name"].strip()
            match = find_category(cfg, name)
            if name and name.lower() != "all" and match is None:
                return 404, {"error": f"no category called {name!r}",
                             "categories": list(cfg.categories)}
            mw.catctl.set_category(match or "")
        else:
            return 400, {"error": "say which: ?name=… or ?step=next / prev"}
        return 200, {"category": cfg.category}
    if action == "volume":
        err = set_volume(mw.vol_sound.spin, params)   # -> set_option("sound_vol")
        return err or (200, {"volume": mw.vol_sound.spin.value()})
    if action == "queue":
        return dispatch_queue(mw, params)
    if action in VOICE_ACTIONS:
        return dispatch_voice(mw, action, params)
    if action in LIVE_ACTIONS:
        return dispatch_live(mw, action, params)
    if action == "mode":
        return dispatch_mode(mw, params)
    if action in APP_ACTIONS:
        return dispatch_apps(mw, action, params)
    if action in ("setups", "setup"):
        return dispatch_setups(mw, action, params)
    if action in streamapi.STREAM_ACTIONS:
        return streamapi.dispatch(mw, action, params)
    if action == "hotkeys":
        on = on_value(params, mw.hkctl.hotkeys_on)
        if on is None:
            return 400, BAD_ON
        mw.hkctl.set_hotkeys_on(on, remote=True)
        return 200, {"hotkeys": mw.hkctl.hotkeys_on}
    if action == "mic_gate":
        on = on_value(params, bool(cfg.mic_gate))
        if on is None:
            return 400, BAD_ON
        set_mic_gate(mw, on)
        return 200, {"mic_gate": bool(cfg.mic_gate)}
    if action in RADIO_ACTIONS:
        return dispatch_radio(mw, action, params)
    if action == "live":
        on = on_value(params, bool(mw.engine.sending))
        if on is None:
            return 400, BAD_ON
        mw.set_sending(on)
        return 200, {"live": bool(mw.engine.sending)}
    if action == "mic":
        on = on_value(params, bool(cfg.mic_enabled))
        if on is None:
            return 400, BAD_ON
        mw.chk_mic.setChecked(on)   # -> on_mic_toggle
        return 200, {"mic": bool(cfg.mic_enabled)}
    if action == "hear":
        on = on_value(params, bool(mw.engine.mic_check))
        if on is None:
            return 400, BAD_ON
        mw.btn_check.setChecked(on)   # -> on_mic_check
        return 200, {"hear": bool(mw.engine.mic_check)}
    if action == "replay":
        from soundboard.audio.engine import SR
        if len(mw.replay.clip()) < int(0.2 * SR):
            return 409, {"error": mw.replay.error or "nothing has played on this PC lately"}
        mw.hkctl.save_replay()
        return 200, {"saved": True}
    # play / stop: one sound, by id or name
    if action == "stop" and not ("id" in params or "name" in params):
        mw.playctl.stop_all()
        return 200, {"stopped": "all"}
    m = find_sound(mw, params)
    if m is None:
        return no_sound(cfg, params)
    if action == "stop":
        mw.engine.stop(m.id)
        for v in playing:   # and a Watch alarm ringing it (its bar clears by itself)
            if v.startswith(m.id + RING):
                mw.engine.stop(v)
        return 200, {"stopped": m.id}
    if m.id not in mw.audio:
        return streamapi.loading_answer(mw, m)
    mw.playctl.play(m.id)
    return 200, {"playing": m.id, "name": m.name}


# --------------------------------------------------------------------------- the queue

def queue_state(mw: MainWindow) -> dict:
    return {"queue": [{"id": s, "name": m.name} for s in mw.playctl._queue
                      if (m := mw.meta(s)) is not None]}


def dispatch_queue(mw: MainWindow, params: dict) -> tuple[int, object]:
    """The play queue (the pad menu's Play next, a category's Play all)."""
    if (params.get("clear") or "").strip() not in ("", "0"):
        mw.playctl._queue.clear()
        mw.playctl._say_queue()
        return 200, queue_state(mw)
    if "category" in params:
        cat = find_category(mw.cfg, params["category"])
        if cat is None:
            return 404, {"error": f"no category called {params['category']!r}",
                         "categories": list(mw.cfg.categories)}
        if not any(m.id in mw.audio for m in mw.cfg.sounds if cat in m.tags):
            return 404, {"error": "no sound to play there"}
        shuffled = (params.get("shuffle") or "").strip().lower() in ("1", "true", "on", "yes")
        mw.playctl.queue_category(cat, shuffled)
        return 200, {"category": cat, **queue_state(mw)}
    if not ("id" in params or "name" in params):
        return 200, queue_state(mw)
    m = find_sound(mw, params)
    if m is None:
        return no_sound(mw.cfg, params)
    if m.id not in mw.audio:
        return 409, {"error": "that sound hasn't loaded (yet)"}
    now = mw.playctl.queue_sound(m.id)   # nothing playing: it plays at once, not after anything
    return 200, {"playing" if now else "queued": m.id, "name": m.name, **queue_state(mw)}


def key_image(mw: MainWindow, params: dict, sounding: list[str]) -> tuple[int, object]:
    from soundboard.control import keyimage

    try:
        size = int(params.get("size") or keyimage.SIZE)
    except ValueError:
        return 400, {"error": "size= takes a number of pixels"}
    size = max(keyimage.MIN_SIZE, min(keyimage.MAX_SIZE, size))
    kind = (params.get("control") or "").strip().lower()
    if kind:
        if kind not in keyimage.CONTROLS:
            return 404, {"error": "no such control", "controls": list(keyimage.CONTROLS)}
        now = {"live": bool(mw.engine.sending), "voice": mw.voice.fx.btn_power.isChecked(),
               "mic": bool(mw.cfg.mic_enabled), "hotkeys": bool(mw.hkctl.hotkeys_on)}
        on = on_value(params, now.get(kind, False)) if params.get("on") else now.get(kind, False)
        if on is None:
            return 400, BAD_ON
        data = base64.b64encode(keyimage.control_png(kind, on, size)).decode("ascii")
        return 200, {"control": kind, "on": on,
                     "look": keyimage.controls_look(mw.cfg.theme, mw.cfg.language),
                     "image": f"data:image/png;base64,{data}"}
    m = find_sound(mw, params)
    if m is None:
        return no_sound(mw.cfg, params)
    flag = (params.get("playing") or "").strip().lower()
    playing = m.id in sounding if flag == "" else flag in ("1", "true", "on", "yes")
    data = base64.b64encode(keyimage.png(m, playing, size)).decode("ascii")
    return 200, {"id": m.id, "look": keyimage.look(m, mw.cfg.theme),
                 "image": f"data:image/png;base64,{data}"}
