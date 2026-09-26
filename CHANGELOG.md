# Changelog

## Unreleased

- Opening the Browser tab no longer makes the window vanish and reappear. The window
  is now GPU-rendered from the start (`QT_WIDGETS_RHI`), so Qt doesn't have to
  rebuild it when the browser first appears.
- The "Only me — click to go live" button label is no longer cut off.

- Only one Soundboard can run. Opening it again brings the existing window to the
  front instead of starting another copy (repeated launches had piled up dozens of
  `pythonw.exe` processes). The lock is a named mutex, which Windows frees if the app crashes.
- Browser → mic no longer stutters every few seconds. Chromium's audio clock and the
  output devices' clocks drift apart, so the browser buffers now track the drift
  (speed nudged by at most 2%, no clicks) instead of running dry.
- Quiet passages in browser audio are streamed too, so sound after a pause in the
  video isn't delayed by re-buffering.

## 0.1.0 — 2026-09-26

First version.

- Sound pads with import (button, drag-and-drop, folders), search, reorder, colours, sizes.
- Per-sound hotkeys, volume, loop and press modes (restart / overlap / toggle).
- Global hotkeys use Windows' `RegisterHotKey`, so they never sit in the input path
  (no stuck keys or input freezes). Warns when another program already owns a hotkey.
- Mixes mic + sounds into a virtual cable at each device's native rate, with soxr resampling.
- Works on any setup: virtual cables (VB-Cable, A/B, Voicemeeter) are detected and
  paired automatically, and the card shows the real device names. With no cable, a
  one-time setup step offers an Install button.
- `install.bat` / `install.ps1`: one-click setup (Python, packages, shortcuts, virtual
  cable). `install-vbcable.ps1` downloads VB-Cable from the official site and checks its
  signature before running it.
- **Browser → mic** tab: a built-in browser whose audio goes live through your mic
  (LIVE toggle, own volume, hear-it-myself). **Record clip** and **Clip last 15s** turn
  what played into new sound pads. Stop all pauses it, and auto push-to-talk covers it.
- Headphone monitoring, loudness levelling, soft limiter.
- Transport bar: play/pause, stop, seek.
- Global stop-all and pause-all hotkeys, auto push-to-talk. Push-to-talk always releases
  the exact key it pressed.
- Volume controls with plain-language labels and typed % (up to 1000%).
- 7-band EQ for voice, sounds or both, with presets.
- Test mode: live mic-output monitor with red banner, and a 6-second record/playback
  check of the real cable output that reports voice/sound presence and balance.
- Simple main panel with a plain-English "How it works" card. Devices, sound options,
  EQ and hotkeys sit under a collapsible ⚙ Advanced section.
- The mouse wheel scrolls the panel and never changes dropdowns, sliders or number boxes.
- Virtual cables are excluded from the mic list, which prevents a feedback loop.
