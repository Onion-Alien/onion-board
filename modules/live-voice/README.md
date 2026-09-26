# Live voice-to-speech (Soundboard module)

Talk normally; Soundboard hears each sentence, turns it into text on your own PC
and says it with a text-to-speech voice. Everyone else hears the TTS voice
instead of yours.

It isn't instant. A line is spoken once you finish saying it, usually 0.5–1.5 s
later depending on your CPU and the model.

## Install

1. Install Python 3.10 or newer from python.org and tick "Add python.exe to PATH".
2. Put this `live-voice` folder in `%APPDATA%\Soundboard\modules\`, or in the
   `modules` folder next to `Soundboard.exe`.
3. Double-click `install.bat`. It creates a private Python environment in
   `.venv` and downloads the speech model (about 300 MB in total).
4. In Soundboard, open the Voice panel and press **Start live voice**.

## Models

`base.en` is the default: fast on any recent CPU. `small.en` is more accurate
but slower. For languages other than English, use `base` or `small` and set the
language in the Voice panel. With an NVIDIA GPU and CUDA, choose the `cuda`
device.

## How it talks to the app

It runs as its own process and talks to the app over a local socket (see
`protocol.py`). The app sends it 16 kHz mic audio and it sends back text. If it
crashes, your mic and sounds keep working. Nothing leaves your PC.
