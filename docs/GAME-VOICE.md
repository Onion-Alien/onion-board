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
  left as they are. (Later rebuilt after the Valorant measurements: see below.)
- **Windows' default mic.** Voice SDKs ask Windows for the *default communication
  device*, which "Set as Default Device" doesn't change; the Setup tab's
  *Game has no microphone setting?* steps (shown on the cable route) now set both.

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
  held: level kept within 2 dB, a steep high-pass near 80 Hz (-19..-25 dB at 70 Hz)
  with a slow tail above it (a bass-heavy song lost 5 dB at 80-100 Hz, 3 at 100-120,
  1.3 at 120-200), the full band up to 10 kHz and a few dB down above, no noise
  suppression or AGC, the start of sounds kept. The bench's `vivox` profile models it
  as a 12th-order high-pass at 80 Hz plus a 2nd-order one at 104 Hz: run on the same
  cable recordings it matches what the second PC heard within 0.7 dB in every band. On *Automatic* Valorant sends only speech: test tones, noise, sweeps
  and speech-shaped noise were never transmitted. Its anti-cheat ignores injected key
  presses, so the app's *Auto push-to-talk* can't hold the key: hold it yourself.
- **A bass-heavy song in Valorant**: sent raw it arrived 7 dB quieter, most of that the
  lost sub-bass (the bottom band 8.5 dB down on the rest). Through the old *Game*
  destination mode (today's *Vivox*) the bass harmonics halved that loss (4 dB), but the mode's
  compressor and limiter sent the song 11 dB quieter to begin with, so it was heard
  8.5 dB quieter than raw.
- **Why, and the fix (99 songs, five pitch ranges, through the `vivox` model):** the
  sounds' levelling measures a song *with* its sub-bass, so an 808 track was levelled
  8–10 dB quieter than a bright one and then lost that sub-bass in the chat; the old
  peak compressor took another 5–9 dB off everything. The modes now cut the sub-bass
  themselves after making the harmonics (`lowcut`), give each sound back the level
  the cut takes from it (worked out per sound when it starts, so a short clip over a
  bass song isn't pushed up with it), and run without compression. Heard level
  against the same song played straight into the cable (median, worst):

  | Pitch range | Old Game mode | New Game mode |
  |---|---|---|
  | super low (808s, bass-boosted) | −11.1 dB (−13) | +0.2 dB (−3) |
  | low | −9.8 dB (−13) | −0.6 dB (−6) |
  | medium | −8.3 dB (−12) | −1.5 dB (−6) |
  | high | −8.3 dB (−11) | −1.0 dB (−5) |
  | super high (chipmunk, monk vocals) | −5.6 dB (−10) | +0.8 dB (−4) |

  Every range now arrives within ~2 dB of the others, the bass reads ~2 dB fuller
  than the raw song on 808 tracks, the mid-band pumping on kicks dropped from
  1.0 to 0.6 dB (raw: 0.4) and the spectral distance from 2.2 to 2.0. Discord and
  Steam got the same treatment (Discord −8.3 → +0.2 dB, Steam −8.6 → −1.8 dB); a
  compressor lost level and added distortion in every range and every chat, so the
  built-in modes run without one.

## One mode per engine (2026-09)

*Who's listening* now has one mode per voice chat engine: Discord, Vivox, Epic Online
Services, Steam voice, Unity voice (Photon / Dissonance) and Low bandwidth (8 kHz).
Each engine was tuned on the same 99 songs (30 s from the middle of each, five pitch
ranges from 808 trap to chipmunk vocals), through the app's real send path (each
sound's levelling and make-up, the mode, phase-aware mono, the limiter) and then the
engine's own mic cleanup and voice gate as it ships (`codec_bench.py --defaults`: the
real WebRTC and RNNoise code in the bench environment) before its codec. Earlier runs
left the cleanup and gate out; with them in, compression and loudness could have
helped (a gate needs level, an automatic gain pumps), so every knob was swept again.

**Sweep** (20 songs, 4 per pitch range; heard level against the same song played
straight into the chat, median dB; *chop* = % of the song's active moments the
listener doesn't get):

| Engine (bench profile) | Cleanup, gate | No mode | 60 Hz cut | 80 Hz cut | 90 Hz cut | + compressor 25 / 50 / 100 % |
|---|---|---|---|---|---|---|
| Epic Online Services (`eos`) | WebRTC NS + AGC | −3.8 | −1.5 | −1.4 | −1.3 | −3.8 / −4.7 / −5.3 |
| Photon (`photon`) | gate −43 dB | −4.8 | −2.8 | −1.7 | −1.7 | −4.4 / −5.5 / −6.3 |
| Dissonance (`dissonance`) | WebRTC NS + AGC, gate −45 dB | −3.8 | −1.4 | −1.2 | −0.8 | −3.5 / −4.4 / −5.0 |
| Browser / WebRTC (`webrtc`) | WebRTC HPF + NS + AGC, gate −30 dB | −3.7 | −1.5 | −1.4 | −1.3 | −3.8 / −4.7 / −5.2 |
| TeamSpeak (`teamspeak`) | WebRTC NS + AGC, gate −40 dB | −3.8 | −1.5 | −1.4 | −1.3 | −3.7 / −4.6 / −5.3 |
| Mumble (`mumble`) | NS + AGC model, gate −24 dB | +0.0 | +0.1 | +0.1 | +0.2 | +0.2 / +0.2 / +0.2 |
| Unreal built-in (`ue_voip`) | gate −26 dB | −4.9 | −2.0 | −1.2 | −1.0 | −3.6 / −4.7 / −5.7 |
| Vivox Siren 7 (`vivox_siren7`) | none | −4.8 | −2.8 | −1.7 | −1.6 | −4.4 / −5.5 / −6.3 |

(Every cut column is with the sub-bass harmonics at 80 % and each sound's level
given back; the compressor columns are on top of the 80 Hz cut.)

- **Every engine wants the same shaping**: cut the sub-bass at 80-90 Hz after making
  the harmonics, give each sound back the level the cut took, no compressor. What
  sets the modes apart is the cut (Discord's high-pass sits at 94 Hz, so 90 there)
  and the codec's ceiling (12 kHz for Steam and Photon, 8 kHz for the low-bandwidth
  codecs). Epic Online Services came out the same as Vivox; it stays its own entry
  so its players find it, with a note to turn its noise suppression off.
- **The compressor never paid.** Even behind an automatic gain it cost 2-5 dB and
  added distortion. Mumble's AGC levels everything anyway, and there a light
  compressor did pump a little less (6.3 → 5.5 dB), for more distortion and less
  bass; not worth a mode of its own, and that AGC is a model.
- **A gate needs level, and the make-up gives it.** A bass-heavy song sent without a
  mode fell under the browser chat's −30 dB gate and was chopped (3 % of the song gone,
  the mid-band wobbling by 18 dB); the 80 Hz cut with its make-up kept it open
  (0.04 %). Unreal's −26 dB gate: 1 % → 0. Mumble's −24 dB: 3.5 % → 1.5 %. A
  compressor put songs back under the gate (browser: 1.2-2.4 %).
- **The ceiling barely matters for the level.** At Photon's 24 kHz the 12 kHz
  low-pass changed nothing measurable; it's there so what you monitor matches what
  they hear. An 8 kHz low-pass for Dissonance only lost detail: at 17 kbps its codec
  still carries more than that.
- **Noise suppression is what hurts, and no mode fixes it.** On every engine with
  WebRTC's suppressor the mid-band pumping sat at 3-4 dB and the spectral distance at
  ~4 dB whatever was sent (Vivox without it: 0.5 and 2.0). Only turning it off in the
  game helps; the game voice chat guide says so.

**The modes on all 99 songs** (heard level against the same song played straight into
the chat, median dB per pitch range: no mode → the engine's mode; each engine's own
cleanup and gate included):

| Mode (engine) | super low | low | medium | high | super high | all |
|---|---|---|---|---|---|---|
| Discord | −8.7 → **+0.7** | −4.6 → **−0.1** | −3.8 → **−1.3** | −2.0 → **−0.7** | +0.7 → **+0.8** | −3.6 → **+0.3** |
| Vivox | −8.7 → **+0.2** | −4.6 → **−0.6** | −3.8 → **−1.5** | −2.0 → **−1.0** | +0.8 → **+0.8** | −3.6 → **+0.0** |
| Epic Online Services | −5.8 → **−1.6** | −4.2 → **−1.1** | −3.0 → **−1.6** | −1.7 → **−0.9** | +1.1 → **+1.3** | −2.2 → **−0.5** |
| Steam voice | −8.8 → **−1.8** | −4.7 → **−1.7** | −4.0 → **−2.0** | −2.2 → **−1.4** | +0.7 → **+0.7** | −3.6 → **−1.3** |
| Unity voice: Photon | −8.8 → **−1.8** | −4.7 → **−1.7** | −4.0 → **−2.0** | −2.2 → **−1.4** | +0.8 → **+0.9** | −3.6 → **−1.3** |
| Unity voice: Dissonance | −5.7 → **−1.1** | −4.2 → **−0.8** | −2.8 → **−1.3** | −1.7 → **−1.3** | +0.9 → **+1.3** | −2.4 → **−0.6** |
| Low bandwidth: Unreal built-in | −8.2 → **−0.6** | −4.7 → **−1.1** | −3.8 → **−1.8** | −2.2 → **−1.3** | +0.6 → **+0.7** | −3.7 → **−0.6** |
| Low bandwidth: Vivox Siren 7 | −8.8 → **−1.5** | −4.7 → **−1.6** | −4.0 → **−2.0** | −2.2 → **−1.5** | +0.7 → **+0.7** | −3.6 → **−1.3** |

Every range of every engine now arrives within about 2 dB of the raw song, and the
super-low range (808s, bass-boosted) gains 4-9 dB. Through Dissonance the Unity mode's
12 kHz ceiling measured the same as full band (−0.6 against −0.7 dB, spectral distance
4.42 against 4.39), so one Unity mode covers Photon and Dissonance.

**Suggesting the mode** (`soundboard/voicesdk.py`). A voice SDK ships as its own library
in the game's install folder, so the program in front is matched by its files: its
exe path is read with `PROCESS_QUERY_LIMITED_INFORMATION` (what Task Manager uses;
anti-cheat allows it), and its install folder (for an Unreal game, three levels above
`Binaries\Win64`) is listed. No module list, no memory read, nothing injected.
Checked against the installs on a test PC: `vivoxsdk.dll` was there in all five Vivox
games (Valorant, League of Legends, Teamfight Tactics, the Riot client, and an Unreal
game whose Vivox plugin sits ten folders deep) and in none of three games without
it; the path query worked on a running game behind anti-cheat. Photon Voice ships
`opus_egpv.dll` in `<Game>_Data\Plugins\x86_64`, Dissonance `DissonanceVoip.dll` in
`Managed\` (from their SDKs and the games' modding docs; no such game was installed
to check). Not suggested, because the files can't tell: Epic Online Services
(`EOSSDK-Win64-Shipping.dll` was also in a single-player game with no voice chat at
all), Steam voice (`steam_api64.dll` is in nearly every Steam game) and
Unreal's built-in voice.

**Who's actually listening** (2026-10). Windows lists the programs recording a device
the same way it lists the ones playing, so the program recording the virtual cable's
far end names the listener directly: Discord, TeamSpeak and Mumble by their exe, a
game by the same library scan as above. It beats the game in front (playing Valorant
while talking in Discord suggests Discord; when both record the cable, the game in
front wins). A browser recording the cable gets the new *Browser voice (WebRTC)* mode:
the same 80 Hz cut as Epic Online Services, whose cleanup is the same WebRTC code (in
the sweep above the browser profile measured −1.4 dB at 80 Hz and −1.3 at 90; it hasn't
had the 99-song run yet). With *Pick the mode by itself* ticked, the picker uses
it as soon as it's found; with nothing listening the mode stays as it is.
