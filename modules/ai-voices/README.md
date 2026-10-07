# AI voices (optional Onion Board add-on)

Talk, and others hear a different person: your words, timing and tone in another
voice, live, on your PC's CPU. It isn't part of Onion Board or its installer; the
Voice tab's *Get AI voices* button downloads it (`AiVoices-module.zip` from this
project's `ai-voices` release, checked against GitHub's SHA-256) and
*Remove AI voices* deletes it again. Its install (`install.bat` does the same) needs
Python 3.12+ and makes its own `.venv` with the pinned `onnxruntime` and `numpy`;
nothing of it runs inside the app.

## How it works

```
app: mic -> talk gate -> 16 kHz -> 127.0.0.1 ──> helper.py (its own Python)
                                                   converter.py: onnxruntime, 1 thread
app: voice chain <- jitter buffer <- 24 kHz  <───  b"B" frames, 20 ms each
```

- `converter.py` runs a streaming export of a **Beatrice 2** voice conversion model:
  every causal convolution keeps its last frames as state, so each 20 ms costs only
  20 ms of new work (about 3 ms on one core of a desktop CPU; real-time factor
  ~0.17). Pitch features and the vocoder's pulse train, noise and post filter are
  numpy.
- The helper uses no CPU while you're quiet: the app sends nothing, so it sleeps.
- About 75 ms behind you: 20 ms chunks, ~32 ms of model look-ahead, a 20 ms buffer.
- If the helper stops, the app covers you with a built-in voice preset (or your
  own voice / silence: *More options*).
- `helper.py --self-test` prints this PC's real-time factor; above 0.5 the Voice tab
  warns that games may stutter.

## The voices

`voices.json` lists them. Each is a **blend of 2–3 speakers** from the pretrained
200-speaker model, plus a formant and pitch setting, so no voice is any one real
person. Never add a voice made to sound like a real, identifiable person.

The app carries the same list (`soundboard/speech/aivoicelist.py`, a test keeps them
equal) and writes it into the installed copy's `voices.json`, with the user's own
voices, so a new blend of speakers the model already has reaches old downloads
without a new release. A voice needing a speaker the model lacks is left out.
`about` and `tags` are for the app's *All voices* window.

## Licences

- Model design, training code and pretrained weights: [beatrice-trainer]
  (MIT licence, Project Beatrice). Its pretrained phone extractor was trained on
  ReazonSpeech, its base voices on LibriTTS-R (CC BY 4.0: the readers of LibriVox
  recordings, via OpenSLR), plus VocalSet and DNS-Challenge data.
- The Beatrice VST's own runtime is closed source and is **not** used here; this
  runtime is our own ONNX export (`tools/stream_model.py`).
- onnxruntime: MIT licence.

The model in `model/` (in the released zip; never committed) isn't this project's own work: it's converted from Project
Beatrice's pretrained models, which their repository releases under the MIT
licence (code *and* pretrained models). Their licence travels with it:
[LICENSE-beatrice.txt](LICENSE-beatrice.txt).

## Rebuilding the model (developers)

Needs torch + torchaudio and a [beatrice-trainer] checkout (with its LFS weights):

```
set BEATRICE_TRAINER=path\to\beatrice-trainer
python tools\export_model.py --out path\to\model          # stream.onnx, speaker.onnx, voices.npz
python ..\..\scripts\make_ai_voices_zip.py --model path\to\model
```

`export_model.py --checkpoint my.pt.gz` exports a model you trained yourself with
beatrice-trainer (e.g. on a free Colab GPU); point `voices.json`'s `mix` at its
speaker numbers.

[beatrice-trainer]: https://huggingface.co/fierce-cats/beatrice-trainer
