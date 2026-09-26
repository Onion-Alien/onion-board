# Changelog

## Unreleased

- Simple main panel; devices, sound options, EQ and hotkeys moved under a
  collapsible ⚙ Advanced section (remembers if you left it open).
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
