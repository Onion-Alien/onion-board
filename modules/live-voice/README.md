# Live voice-to-speech (Soundboard module)

Talk normally; Soundboard hears each sentence, turns it into text on your own PC
and says it with a text-to-speech voice. Everyone else hears the TTS voice
instead of yours.

It isn't instant. A line is spoken once you finish saying it, usually 0.5–1.5 s
later depending on your CPU and the model.

## Install

It comes with Soundboard (in the `modules` folder next to `Soundboard.exe`).

1. Install Python 3.12 or newer from python.org and tick "Add python.exe to PATH".
2. In Soundboard, open the **Voice** tab and press **Install speech recognition**.
   It creates a private Python environment in this folder's `.venv` and downloads
   the speech model (about 300 MB in total). `install.bat` here does the same.
3. Press **Start talking as the voice**.

## Models

`base.en` is the default: fast on any recent CPU. `small.en` is more accurate
but slower. For languages other than English, use `base` or `small` and set the
language in the Voice tab. With an NVIDIA GPU and CUDA, choose the `cuda`
device.

## Speaking another language

The `translate-*` add-ons (Chinese, Spanish, French, German, Russian) let the
voice say what you said in that language. Pick one under **Speak in** in the
Voice tab and press **Download** (65–195 MB, once). The app then starts this
helper with `--translate <folder>`: each English sentence is translated on your
PC with that CTranslate2 model before it's spoken. The models come from the
Argos Translate package index (mostly OPUS-MT, CC BY 4.0).

## How it talks to the app

It runs as its own process and talks to the app over a local socket (see
`protocol.py`). The app sends it 16 kHz mic audio and it sends back text. If it
crashes, your mic and sounds keep working. What you say never leaves your PC
(only the one-time model download goes online).
