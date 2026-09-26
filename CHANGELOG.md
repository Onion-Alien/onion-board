# Changelog

## Unreleased

- **Fix: keys getting stuck / input freezing.** Dropped the `keyboard` package,
  whose low-level hook put the app in the path of every keypress. While the app
  was busy (e.g. starting up) Windows stalled input, and a held key stayed
  "down". Hotkeys now use `RegisterHotKey`, which can't block input.
- Fix: auto push-to-talk always releases the exact key it pressed, even if the
  PTT setting changes while it's held.
- Warns when another program already owns a chosen hotkey.
- Simple main panel; devices, sound options, EQ and hotkeys moved under a
  collapsible ⚙ Advanced section (remembers if you left it open).
- Works on any setup: virtual cables (VB-Cable, A/B, Voicemeeter) are detected
  and paired automatically, and the card shows the real device names.
- If there's no virtual cable, the app shows a one-time setup step with an
  Install button.
- `install.bat` / `install.ps1`: one-click setup (Python, packages, shortcuts,
  virtual cable). `install-vbcable.ps1` downloads VB-Cable from the official site
  and checks its signature before running it.
- The mouse wheel no longer changes dropdowns, sliders or number boxes. It
  scrolls the panel; values change only by clicking or dragging.

## 0.1.0 — 2026-09-26

First version.

- Sound pads with import (button, drag-and-drop, folders), search, reorder, colours, sizes.
- Per-sound hotkeys, volume, loop and press modes (restart / overlap / toggle).
- Mixes mic + sounds into VB-Cable at each device's native rate, with soxr resampling.
- Headphone monitoring, loudness levelling, soft limiter.
- Transport bar: play/pause, stop, seek.
- Global stop-all and pause-all hotkeys, auto push-to-talk.
- Volume controls with plain-language labels and typed % (up to 1000%).
- 7-band EQ for voice, sounds or both, with presets.
- Test mode: live mic-output monitor with red banner, and a 6-second record/playback
  check of the real cable output that reports voice/sound presence and balance.
- Plain-English "How it works" panel; device pickers tucked under ⚙.
- Virtual cables are excluded from the mic list, which prevents a feedback loop.
