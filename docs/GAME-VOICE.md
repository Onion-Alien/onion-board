# What game voice chat does to your sounds

Reference for the bench profiles in `soundboard/codecsim.py` (`scripts/codec_bench.py
--list` prints them) and what the bench found. Discord was measured in a real call
(`scripts/discord_roundtrip.py`); the game profiles come from each stack's source
code or SDK docs where those are public, and are marked *estimate* where not.

## The stacks

| Stack | Games | Codec as sent | Cleanup (defaults) | Sources |
|---|---|---|---|---|
| Steam voice | CS2, Dota 2, TF2, Deep Rock Galactic | Opus fed 24 kHz mono (12 kHz ceiling), 20 ms | Steam's own voice settings | [ISteamUser](https://partner.steamgames.com/doc/api/isteamuser), [reversing the codec](https://zhenyangli.me/posts/reversing-steam-voice-codec/) |
| Vivox | Valorant, League, Rainbow Six Siege, Overwatch 2 | Opus 48 kHz, 32–40 kbps (Siren 14 / Siren 7: 16 / 8 kHz ceiling) | noise suppression + AGC on, voice gate with 2 s hangover | [codecs](https://docs.unity.com/en-us/vivox-unity/developer-guide/troubleshooting/codec-comparison-unity), [VAD](https://docs.unity.com/en-us/vivox-core/developer-guide/troubleshooting/voice-activity-detection-core), [3D](https://docs.unity.com/en-us/vivox-unity/developer-guide/channels/positional-channel-properties) |
| Epic Online Services | Fortnite | *estimate*: Opus 48 kHz ~32 kbps, WebRTC-style cleanup | | [EOS voice](https://www.epicgames.com/site/news/epic-online-services-launches-free-in-game-voice-and-easy-anti-cheat) |
| Unreal built-in | Unreal games without Steam / EOS / Vivox voice | *estimate*: 16 kHz (8 kHz ceiling) | noise gate 0.08 | [VoiPSampleRate](https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Engine/Sound/UAudioSettings/VoiPSampleRate) |
| Photon Voice | Phasmophobia | Opus 24 kHz (12 kHz ceiling), 30 kbps, 20 ms | gate 0.01, 500 ms release | [Recorder](https://doc.photonengine.com/voice/v2/getting-started/recorder) |
| Dissonance | Lethal Company | Opus ~17 kbps, 40 ms | WebRTC VAD, Speex AGC + noise removal | [VoiceSettings](https://github.com/placeholder-software/Dissonance/blob/master/docs/Reference/Audio/VoiceSettings.md), [pipeline](https://martindevans.me/voip/2017/02/19/Dissonance-Voip-Pipeline/) |
| Mumble | Mumble servers | Opus 48 kHz, 40 kbps CBR, audio mode | Speex noise suppression + AGC, amplitude voice activation | [Settings.h](https://github.com/mumble-voip/mumble/blob/master/src/mumble/Settings.h) |
| FiveM + pma-voice | GTA V roleplay | Opus 48 kHz, 48 kbps CBR, audio mode, 40 ms | WebRTC high-pass, noise suppression High, AGC; radio band 389–3248 Hz | [MumbleAudioInput.cpp](https://github.com/citizenfx/fivem/blob/master/code/components/voip-mumble/src/MumbleAudioInput.cpp), [pma-voice](https://github.com/AvarianKnight/pma-voice/blob/main/shared.lua) |
| Simple Voice Chat | Minecraft | Opus 48 kHz voip, 20 ms | RNNoise + AGC, push-to-talk; linear fade to 48 blocks | [source](https://github.com/henkelmax/simple-voice-chat) |
| VRChat | VRChat | *estimate*: Opus 48 kHz ~30 kbps | RNNoise, 5% activation; +15 dB, 25 m, distance low-pass | [player audio](https://creators.vrchat.com/worlds/udon/players/player-audio/) |
| WebRTC | Among Us (BetterCrewLink), Roblox | Opus ~32 kbps | browser high-pass, noise suppression, AGC | [BetterCrewLink](https://github.com/OhMyGuus/BetterCrewLink/blob/nightly/src/renderer/voice/AudioController.ts) |
| TeamSpeak | TeamSpeak 3 / 5 | Opus Voice q6 (28.7 kbps) | noise removal + AGC | [codec table](https://teamspeakdocs.github.io/ClientSDK/client_html/ar01s14.html) |

Lethal Company's occlusion and walkie-talkie filters come from its decompiled
`OccludeAudio.cs` / `StartOfRound.cs`; `soundboard/proxsim.py` has the numbers.

## What the bench found (2026-09)

- **The codecs themselves are gentle.** Through the codec alone a song loses a
  spectral distance of 1–2 dB in every stack; the 12 kHz (Steam, Photon) and 8 kHz
  (Unreal, Siren 7) ceilings are the only big cut.
- **The cleanup is what hurts.** With each game's default cleanup on, the real
  WebRTC noise suppressor pulls steady music down 12–15 dB (the old model said
  4), and its AGC pumps quiet parts up ~7 dB.
- **AI denoisers wipe out music.** RNNoise (VRChat, Simple Voice Chat) left a song
  14–21 dB quieter and badly smeared, and removed the test tones entirely. Only
  turning the denoiser off helps; no send mode saves it.
- **Voice gates cut quiet sounds.** Unreal's noise gate, Mumble's voice activation
  and VRChat's threshold silenced quiet test sounds completely. Push-to-talk (the
  app's *Auto push-to-talk*) avoids it.
- **The send modes are a small win, not a fix.** Across the stacks every mode keeps
  ~4 dB more bass for ~2.7 dB of deliberate change; where the chat runs an AGC they
  also cut its damage (6.4 → 4.5). None beats the others everywhere, so they were
  left as they are.
- **Windows' default mic.** Voice SDKs ask Windows for the *default communication
  device*, which "Set as Default Device" doesn't change; the app's
  *Game has no microphone setting?* steps now set both.

- **Steam voice, measured** (`scripts/steam_voice_roundtrip.py`): Steamworks reports
  24 kHz as its voice rate, confirming the 12 kHz ceiling. Its capture gates the
  input on its own, even with Steam's threshold set to Off: steady tones never got
  through, and full-level speech only in bursts (1.4 s of 20 s). Sounds in Steam
  games need to be loud and voice-like; quiet intros and steady tones can vanish.
  The gating was too erratic to measure a full frequency response.
- **Windows' capture path is clean** (`scripts/game_capture.py --resample
  --ducking`): games opening the cable at 44.1 / 32 / 24 / 16 kHz or through MME
  lose at most 1.2 dB, with no more converter junk than the 48 kHz reference. A
  plain capture stream on the communications mic didn't duck the sounds going into
  the cable (a stream tagged as a call might; not tested).

- **Valorant, measured in a real party** (`scripts/game_roundtrip.py` on one PC,
  `scripts/game_listener.py` recording the second PC's Valorant). With push-to-talk
  held: level kept within 2 dB, a high-pass near 87 Hz (-19..-25 dB at 70 Hz, flat
  from 120 Hz), the full band up to 10 kHz and a few dB down above, no noise
  suppression or AGC, the start of sounds kept. The bench's `vivox` profile now uses
  these numbers. On *Automatic* Valorant sends only speech: test tones, noise, sweeps
  and speech-shaped noise were never transmitted. Its anti-cheat ignores injected key
  presses, so the app's *Auto push-to-talk* can't hold the key: hold it yourself.
- **A bass-heavy song in Valorant**: sent raw it arrived 7 dB quieter, most of that the
  lost sub-bass (the bottom band 8.5 dB down on the rest). Through the *Game*
  destination mode the bass harmonics halved that loss (4 dB), but the mode's
  compressor and limiter sent the song 11 dB quieter to begin with, so it was heard
  8.5 dB quieter than raw. The Game mode should keep the harmonics and lose the
  squeeze.
