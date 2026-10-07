# The performance suite (`python -m perf`)

It runs the real Onion Board (and, if you give it an Onion Watch checkout, the
Triggers add-on and standalone Onion Watch) in a child process, steps it through
things people actually do, and measures from the outside what each step costs: CPU,
RAM, threads, handles, GDI/USER objects, disk writes, and how late the audio
callbacks ran. Windows only (it reads the process with Win32 calls through ctypes;
on other systems it says so and exits 0). No new dependencies.

It is **not** part of `pytest`: pytest only collects `tests/`. The suite's own maths
and process readers are tested in `tests/test_perf_metrics.py`.

## Running it

From the repo folder:

```powershell
.venv\Scripts\python -m perf --tier quick                 # ~1.5 min
.venv\Scripts\python -m perf --tier quick --watch-src ..\onion-watch   # + Triggers, Onion Watch
.venv\Scripts\python -m perf --tier full                  # ~5 min
.venv\Scripts\python -m perf --tier soak --minutes 30     # tray idle, for leaks
.venv\Scripts\python -m perf --tier frozen --app-dir ..\App --watch-exe <path>\OnionWatch.exe
```

Useful flags: `--out DIR` (default: a new folder under `%TEMP%\onionboard-perf`),
`--compare OLD\report.json` (adds a before → after column), `--budget FILE` /
`--no-budget`, `--only board,triggers,watch`, `--env KEY=VALUE` (extra environment
for the measured app, e.g. `OPENBLAS_NUM_THREADS=1`), `--no-event-counts` (leaves
out the in-app paint/timer counter, which costs a little CPU itself).

Measure on a quiet PC: another test suite or a game running at the same time
moves the CPU and audio-lateness numbers a lot. RAM, threads and handles are steady.

## What's safe

Nothing it does is seen or heard:

- Its own throwaway `APPDATA` / `LOCALAPPDATA` / `TEMP` under `--out`, its own
  single-instance name; the child refuses to start if the app's data folder isn't
  in there.
- Qt's offscreen platform: no window on any screen, no focus taken.
- Audio goes through `perf/fakeaudio.py`: the app's real callbacks on a thread at
  the device's pace, but no real device. The mic is a made-up voice.
- Global hotkeys, key presses, MIDI, autostart, shortcuts, the mic effect's admin
  step, message boxes, the update check and the usage count are stubbed. Offline
  mode is on and Python sockets can only reach 127.0.0.1.
- `frozen` runs the built exes with `--selftest` only.

A `--real-window` tier (real windows parked off every monitor, to see GPU/driver
costs offscreen Qt can't) is started in the code but **not finished and switched
off**: it would open real windows, so it needs the user's OK before anyone works
on it or runs it.

## The tiers

| tier | takes | what |
|---|---|---|
| quick | ~1.5 min (+ ~1 min with `--watch-src`) | 20 sounds, every scenario below once, 4 s each |
| full | ~5 min (+ ~2 min with `--watch-src`) | 100 sounds, 8 s each, longer leak loop, stereo mic, heavy voice presets; Triggers with 0, 10 and 50 triggers |
| soak | `--minutes` + ~30 s | hidden in the tray, a sample every 10 s; reports growth per hour |
| frozen | ~30 s | built `OnionBoard.exe` / `OnionWatch.exe --selftest`: peak RAM, threads, handles, time to exit, install folder size and its 20 biggest files |

## The scenarios (board)

| scenario | what happens |
|---|---|
| cold_start | process start → window ready with the sounds loaded |
| idle_front / idle_behind | idle on the Sounds tab, in front / behind another program |
| minimised, tray, shown_again | the window minimised, hidden in the tray, shown again |
| import_sounds | imports 8 short and 2 long (150 s) generated sounds; disk writes |
| play_overlap, play_rapid | 3 sounds at once; 20 rapid hotkey-style plays |
| fx_preview | effects preview on 5 pads (checks the preview cache lets go) |
| tabs_tour | opens every tab once (`tab_open_ms` = first-show time per tab) |
| dialogs | Settings twice and two Edit dialogs |
| voice_preset (+ voice_heavy, stereo_mic in full) | the voice changer on and off |
| mic_check_front / _behind | the mic check banner on, in front and behind |
| apps_tab_shown / _left | the Apps tab's live meters, then back to Sounds |
| route_mic | sending through the mic effect instead of the cable |
| leak_loop | plays, preview, Settings, tab switches, pad rebuild, N times; growth per loop |
| idle_end | tray idle at the end: does it settle back down? |

With `--watch-src` (an Onion Watch checkout; its add-on zip is built with that
checkout's `scripts/build_module.py`): `triggers-N/…` runs the board with the
add-on and N triggers on a stand-in 1920×1080 screen (watching off, watching
with the tab hidden, the tab shown, watching from the tray), and `watch/…` runs
standalone Onion Watch (window shown, tray, watching from the tray).

## Reading the report

`report.md` (and `report.json` with every number) in the `--out` folder: a table
per child process, one row per scenario.

- **CPU % core**: CPU cycles used during the step, as % of one core (100 = one
  core flat out). Idle should be a few %.
- **private MB**: memory only this process holds (what Task Manager's "Memory"
  column shows); **RAM (WS)** is what's in RAM right now.
- **threads**, **handles**, **GDI/USER**: should stay flat across steps.
- **disk write MB**: written during the step.
- **audio late p99 / callback p99**: how late the audio callbacks started and how
  long they ran (99th percentile, ms); **late blocks** would have been audible
  glitches on a real device.
- Under the table, per step: CPU and threads by group (the module each thread
  started in: qt, openblas, portaudio, gpu driver…, or the Python thread's name),
  paints and timer events per second, widget/object counts, and for the loops the
  growth per loop (a steady climb in private MB, handles or Python objects is a leak).

## Budgets

`perf/budgets.json` holds a limit per tier, scenario and metric, plus a
`tolerance` (0.5 = 50 % over the limit is still fine). Over budget: the runner lists
what and exits 1. The limits are **initial**, set generously from origin/main on
2026-10-07 before the perf fixes landed; tighten them as those land.
