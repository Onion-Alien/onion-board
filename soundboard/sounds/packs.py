"""Free sound packs: ready-made boards (a GM's tavern and battle sounds…) anyone can add
in one click from the Sounds tab's Backup menu (*Free sound packs*).

The list is packs/catalog.json in the project's repository, read fresh each time the
window opens (a copy of the packs known when this version was built, BUILT_IN, stands
in when it can't be read). Every pack is a zip in Onion Board's own backup format
(docs/BACKUP-FORMAT.md) uploaded to one of the project's GitHub releases: a pack is
only ever fetched from there, over HTTPS, and only kept when its SHA-256 matches the
one the list gives, so nobody can swap a pack's sounds after it was checked.

A pack can also be only links (a "links" list in place of the zip's url and sha256):
Myinstants sounds' MP3s, each fetched from that site when Add is pressed, the way a
pasted Myinstants link is (soundboard.online.ytdl: its own switch, Tor and proxy
settings), then put in a zip of the same format on this PC (download_links). None of
it is stored by the project; a link that has gone is skipped and counted. Myinstants
is a free site: its links are fetched gently (_Pace: two at a time, spaced out, every
link waiting when it says "too many requests"), and one that failed for now is tried
again a few times, each wait longer (_fetch_link).

Anyone can share a pack: packs/README.md says how (a GitHub form; every sound must be
CC0, so whoever adds it can use it anywhere). The requests carry nothing about the
user beyond what any HTTPS request does, and they have their own switch in Settings >
Privacy & security (FEATURE)."""
from __future__ import annotations

import json
import logging
import re
import shutil
import threading
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from soundboard.core import backup, errors, updates
from soundboard.sounds import library
from soundboard.online import net, netlog
from soundboard.i18n import _

log = logging.getLogger(__name__)

FEATURE = "sound_packs"   # its switch in Settings > Privacy & security (soundboard.online.net)
CATALOG_URL = (f"https://raw.githubusercontent.com/{updates.REPO}/main/packs/catalog.json")
# where people share a pack: a GitHub form that asks for the link and the licence
SHARE_URL = f"https://github.com/{updates.REPO}/issues/new?template=sound-pack.yml"
RULES_URL = f"https://github.com/{updates.REPO}/blob/main/packs/README.md"
MAX_SIZE = 300 << 20     # the biggest pack the app downloads (the GM pack is ~28 MB)
PREVIEW_MAX = 4 << 20    # a pack's preview: a few short sounds (ours are ~0.4 MB)
SAMPLES = 6              # at most this many of a preview's sounds are shown
CATALOG_LIMIT = 1 << 20  # the list is a few KB
ID_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")
MAX_LINKS = 300          # a links pack's sounds
LINK_WORKERS = 2         # links fetched at once
LINK_GAP = 0.5           # seconds between two links starting
LINK_RETRY_WAITS = (2, 5, 15)   # the waits before each new try of a link that failed for now
LINK_MAX_WAIT = 60       # the longest a "too many requests" (its Retry-After) is waited for
LINK_GIVE_UP = 3         # links refused with "too many requests" after every try: stop there


@dataclass(frozen=True)
class Link:
    """One sound of a links pack: its name, its Myinstants MP3 and its category."""
    name: str
    url: str
    category: str = ""


def _link_ok(url: str) -> bool:
    """A Myinstants sound's MP3, nothing else (the list is public: no other site, no
    query, no name that could leave the folder it's saved in)."""
    from soundboard.online.ytsites import MYINSTANTS
    leaf = url.removeprefix(MYINSTANTS + "/media/sounds/")
    return (leaf != url and len(leaf) > 4 and leaf.lower().endswith(".mp3")
            and not any(c in leaf for c in '/\\?#:') and ".." not in leaf)


def _links(raw) -> list[Link]:
    out, seen = [], set()
    for d in raw[:MAX_LINKS] if isinstance(raw, list) else []:
        try:
            link = Link(str(d["name"]).strip()[:60], str(d["url"]).strip(),
                        str(d.get("category") or "").strip()[:40])
        except (KeyError, TypeError, AttributeError):
            continue
        if link.name and _link_ok(link.url) and link.url not in seen:
            seen.add(link.url)
            out.append(link)
    return out


@dataclass
class Pack:
    id: str            # "gm-starter": its zip's name in the app folder's "packs"
    name: str
    description: str
    url: str           # a file on one of the project's GitHub releases
    sha256: str
    size: int = 0      # bytes
    sounds: int = 0
    license: str = "CC0"
    author: str = ""
    emoji: str = "📦"   # the pack's picture in the window
    categories: list[str] = field(default_factory=list)
    # what kind of pack it is, for the window's filters ("Memes", "Streaming"…)
    tags: list[str] = field(default_factory=list)
    # a links pack (no url / sha256): its sounds' Myinstants links, fetched on Add
    links: list[Link] = field(default_factory=list)
    # a few of its sounds, cut short, with their pictures (a small zip in the backup
    # format next to the pack): "Listen first" in the window. Optional.
    preview_url: str = ""
    preview_sha256: str = ""
    preview_size: int = 0

    @property
    def path(self) -> Path:
        """Where it's downloaded to. Importing it moves it in as the kept pack
        (backup.keep_pack), so it's never stored twice."""
        return library.APP_DIR / "packs" / f"{self.id}.zip"

    def downloaded(self) -> bool:
        """Fetched (and checked) before: adding it again just skips what's there."""
        return self.path.is_file() or backup.kept_free_pack(self.id) is not None


# the meme pack: (name, category, its MP3 on Myinstants), from Myinstants' most-played
_MEMES = [
    ("Vine boom", "Reactions", "vine-boom.mp3"),
    ("Bruh", "Reactions", "movie_1.mp3"),
    ("Anime wow", "Reactions", "anime-wow-sound-effect.mp3"),
    ("MLG air horn", "Gaming", "mlg-airhorn.mp3"),
    ("Emotional damage", "Reactions", "emotional-damage-meme.mp3"),
    ("Metal pipe", "Fails", "metal-pipe-clang.mp3"),
    ("Wrong buzzer", "Fails", "wrong-answer-sound-effect.mp3"),
    ("Taco Bell bong", "Reactions", "taco-bell-bong-sfx.mp3"),
    ("Get out (Tuco)", "Reactions", "tuco-get-out.mp3"),
    ("Roblox oof", "Gaming", "roblox-death-sound_1.mp3"),
    ("SpongeBob fail", "Fails", "spongebob-fail.mp3"),
    ("Fahhh", "Reactions", "fahhhhhhhhhhhhhh.mp3"),
    ("Sad violin", "Fails", "tf_nemesis.mp3"),
    ("Rizz", "Vine & TikTok", "rizz-sound-effect.mp3"),
    ("Censor beep", "Reactions", "censor-beep-1.mp3"),
    ("Among Us role reveal", "Gaming", "among-us-role-reveal-sound.mp3"),
    ("Ding", "Reactions", "ding-sound-effect_2.mp3"),
    ("Fortnite death", "Gaming", "tmp_7901-951678082.mp3"),
    ("Bone crack", "Fails", "bone-crack.mp3"),
    ("Metal Gear alert", "Gaming", "tindeck_1.mp3"),
    ("Windows XP error", "Classic memes", "erro.mp3"),
    ("Price is Right losing horn", "Fails", "the-price-is-right-losing-horn.mp3"),
    ("Shut up!", "Reactions", "shutup.swf.mp3"),
    ("Lizard", "Vine & TikTok", "lizard-button.mp3"),
    ("DJ air horn", "Music", "dj-airhorn-sound-effect-kingbeatz_1.mp3"),
    ("What da dog doin", "Vine & TikTok", "yt1s_wU4BGgD.mp3"),
    ("Undertaker bell", "Classic memes", "undertakers-bell_2UwFCIe.mp3"),
    ("Outro song", "Music", "outro-song_oqu8zAg.mp3"),
    ("Oh hell nah", "Reactions", "oh-my-god-bro-oh-hell-nah-man.mp3"),
    ("Dun dun dunnn", "Music", "dun-dun-dun-sound-effect-brass_8nFBccR.mp3"),
    ("Huh? (Ceeday)", "Reactions", "ceeday-huh-sound-effect.mp3"),
    ("Law and Order dun dun", "Music", "dun_dun_1.mp3"),
    ("Baby laughing", "Reactions", "baby-laughing-meme.mp3"),
    ("Chicken jockey", "Gaming", "chicken-jockey.mp3"),
    ("To be continued", "Music", "untitled_1071.mp3"),
    ("Spider-Man meme song", "Music", "spiderman-meme-song.mp3"),
    ("Mario jump", "Gaming", "maro-jump-sound-effect_1.mp3"),
    ("Rehehehe", "Reactions", "rehehehe.mp3"),
    ("Sad trombone", "Fails", "sadtrombone.swf.mp3"),
    ("FBI open up", "Classic memes", "fbi-open-up-sfx.mp3"),
    ("Pluh", "Vine & TikTok", "pluh.mp3"),
    ("Snore mimimimi", "Classic memes", "snore-mimimimimimi.mp3"),
    ("Womp womp womp", "Fails", "downer_noise.mp3"),
    ("Oh no no no laugh", "Reactions", "oh-no-no-no-no-laugh.mp3"),
    ("Run (Vine)", "Vine & TikTok", "run-vine-sound-effect.mp3"),
    ("Minecraft hurt", "Gaming", "classic_hurt.mp3"),
    ("Bad to the bone", "Music", "bad-to-the-bone.mp3"),
    ("Noooo!", "Reactions", "nooo.swf.mp3"),
    ("Oh brother, this guy stinks", "Vine & TikTok", "oh-brother-this-guy-stinks.mp3"),
    ("Hello there", "Classic memes", "obi-wan-hello-there.mp3"),
    ("Yippee", "Reactions", "yippee-tbh.mp3"),
    ("Augh", "Vine & TikTok", "aughhhhh-aughhhhh.mp3"),
    ("Nope", "Reactions", "engineer_no01.mp3"),
    ("Baba Booey", "Classic memes", "bababooey-sound-effect.mp3"),
    ("Yeet", "Vine & TikTok", "yeet-sound-effect.mp3"),
    ("Crickets", "Fails", "crickets.swf.mp3"),
    ("Windows XP shutdown", "Classic memes", "preview_4.mp3"),
    ("Aww", "Reactions", "studio-audience-awwww-sound-fx.mp3"),
    ("Lego Yoda death", "Gaming", "lego-yoda-death-sound-effect.mp3"),
    ("Oh my god", "Reactions", "oh-my-god-meme.mp3"),
    ("Erm what the sigma", "Vine & TikTok", "erm-what-the-sigma_su7GnzC.mp3"),
    ("Mission failed", "Gaming", "dank-meme-compilation-volume-17_cutted.mp3"),
    ("Leeroy Jenkins", "Classic memes", "leroy.swf.mp3"),
    ("Rimshot", "Music", "badumtss.swf.mp3"),
    ("Inception", "Music", "inceptionbutton.mp3"),
    ("My name is Jeff", "Classic memes", "ringtone_20.mp3"),
    ("What are you doing in my swamp", "Classic memes", "what-are-you-doing-in-my-swamp-.mp3"),
    ("Sitcom laugh", "Reactions", "sitcom-laughing-1.mp3"),
    ("We do not care", "Vine & TikTok", "we-do-not-care_phB0mEB.mp3"),
    ("Bonk", "Fails", "bonk_BEtiM8g.mp3"),
    ("A few moments later", "Classic memes", "a-few-moments-later-hd.mp3"),
    ("Extremely loud wrong buzzer", "Fails", "extremely-loud-incorrect-buzzer_0cDaG20.mp3"),
    ("Another one", "Music", "another-one_dPvHt2Z.mp3"),
    ("Tactical nuke incoming", "Gaming", "tactical-nuke.mp3"),
    ("Hitmarker", "Gaming", "hitmarker_2.mp3"),
    ("Wilhelm scream", "Classic memes", "wilhelmscream.mp3"),
    ("Wasted (GTA V)", "Gaming", "gta-v-death-sound-effect-102.mp3"),
    ("Hell naw dog", "Reactions", "hell-naw-dog.mp3"),
    ("Yeah boiii", "Classic memes", "yeah-boiii-i-i-i.mp3"),
    ("Bazinga!", "Classic memes", "bazinga.swf.mp3"),
    ("Deja vu", "Music", "deja-vu.mp3"),
    ("Let's gooo", "Reactions", "vibez-lets-go.mp3"),
    ("Over 9000!", "Classic memes", "over9000.swf.mp3"),
    ("This is Sparta!", "Classic memes", "thisissparta.swf.mp3"),
    ("Nani?!", "Classic memes", "nani_Pmxf5n3.mp3"),
    ("Tuturu", "Gaming", "tuturu_1.mp3"),
    ("Bing chilling", "Vine & TikTok", "bing-chilling_fcdGgUc.mp3"),
    ("Darth Vader noooo", "Classic memes", "nooo.mp3"),
    ("Trololo", "Music", "trollolol.swf.mp3"),
    ("Huh cat", "Vine & TikTok", "huh-cat.mp3"),
    ("Careless whisper", "Music", "careless_whispers.mp3"),
    ("Nelson's ha-ha", "Classic memes", "the-simpsons-nelsons-haha.mp3"),
    ("That was easy", "Reactions", "that_was_easy.mp3"),
    ("Coffin dance", "Music", "y2mate-mp3cut_sRzY6rh.mp3"),
    ("Directed by Robert B. Weide", "Music", "directed-by-robert-b_voI2Z4T.mp3"),
    ("Boom! Headshot!", "Gaming", "boomheadshot.swf.mp3"),
    ("Dramatic chipmunk", "Classic memes", "dramatic.swf.mp3"),
    ("Why are you running?", "Vine & TikTok", "why-are.mp3"),
    ("Super Mario death", "Gaming", "super-mario-death-sound-sound-effect.mp3"),
    ("Zelda item get", "Gaming", "139-item-catch.mp3"),
    ("Illuminati confirmed", "Music", "x-files-theme-song-copy.mp3"),
    ("Za Warudo", "Gaming", "hd-stardust-crusaders-za-warudo_1.mp3"),
    ("Owen Wilson wow", "Reactions", "6_1Njp68r.mp3"),
    ("Sonic ring", "Gaming", "26f8b9_sonic_ring_sound_effect.mp3"),
]

# the packs known when this version was built: shown when the list can't be read
# the gaming sounds pack, the same way (Myinstants' most-played)
_GAMING = [
    ("Mario coin", "Nintendo", "super-mario-coin-sound.mp3"),
    ("Zelda chest opening", "Nintendo", "zelda-chest-opening-and-item-catch.mp3"),
    ("Emergency meeting (Among Us)", "Mobile games", "emergency-meeting-sound-among-us.mp3"),
    ("Finish him!", "Fighting games", "finish-him.mp3"),
    ("Minecraft XP", "Minecraft & Roblox", "orb.mp3"),
    ("Bomb has been planted (CS)", "Shooters", "bomb-has-been-planted-sound-effect-cs-go.mp3"),
    ("Hey, listen! (Zelda)", "Nintendo", "hey_listen.mp3"),
    ("Pikmin!", "Nintendo", "pikmin-gcn.mp3"),
    ("Objection! (Ace Attorney)", "Nintendo", "phoenix-objection.mp3"),
    ("It's-a me, Mario!", "Nintendo", "its-me-mario.mp3"),
    ("Mario 1-up", "Nintendo", "mario-1-up.mp3"),
    ("Waluigi wah", "Nintendo", "waluigi_wahring2mob.mp3"),
    ("Nintendo Switch click", "Nintendo", "switch-sound.mp3"),
    ("Pokemon level up", "Nintendo", "12_3.mp3"),
    ("Mii Channel music", "Nintendo", "mii-channel-music.mp3"),
    ("Beedle: thank you!", "Nintendo", "ww_beedle_thankyou.mp3"),
    ("Pikachu thunderbolt", "Nintendo", "pikachu-thunderbolt.mp3"),
    ("Pokemon battle", "Nintendo", "pokemon-battle.mp3"),
    ("Mario star power", "Nintendo", "super-mario-bros-nes-music-star-theme-cut-mp3.mp3"),
    ("Mario pipe", "Nintendo", "super-mario-bros.mp3"),
    ("Thwomp (Mario 64)", "Nintendo", "super-mario-64-thwomp-sound-online-audio-converter.mp3"),
    ("Mario oof", "Nintendo", "sm64_mario_oof.mp3"),
    ("Mario power-up", "Nintendo", "01-power-up-mario.mp3"),
    ("Mario Kart race start", "Nintendo", "mariostart.mp3"),
    ("Pokemon heal", "Nintendo", "111-pokemon-recovery.mp3"),
    ("Mario yahoo", "Nintendo", "super-mario-64-yahoo-sound.mp3"),
    ("Who's that Pokemon?", "Nintendo", "whos-that-pokemon_.mp3"),
    ("Zelda secret", "Nintendo", "ringtones-zelda-1.mp3"),
    ("Kirby falling", "Nintendo", "kirby-falling.mp3"),
    ("Nice shot! (Wii Sports)", "Nintendo", "nice-shot-wii-sports_DJJ0VOz.mp3"),
    ("Majora's Mask bell", "Nintendo", "mm_clocktower_bell.mp3"),
    ("Mario mushroom", "Nintendo", "super_mario_bros_mushroom_sound_effect_58k.mp3"),
    ("Caught a Pokemon!", "Nintendo", "06-caught-a-pokemon.mp3"),
    ("Poyo! (Kirby)", "Nintendo", "kirby-poyo.mp3"),
    ("Pokemon item found", "Nintendo", "pokemon-red_blue_yellow-item-found-sound-effect.mp3"),
    ("Mario game over", "Nintendo", "super-mario-bros_2.mp3"),
    ("Oh, banana! (Donkey Kong)", "Nintendo", "donkey-kong-64-oh-banana.mp3"),
    ("Let's-a go! (Mario 64)", "Nintendo", "sm64_mario_lets_go.mp3"),
    ("Zelda rupee", "Nintendo", "rupee-collect.mp3"),
    ("Hai! (Kirby)", "Nintendo", "kirby009.mp3"),
    ("Roblox explosion", "Minecraft & Roblox", "roblox-explosion-sound.mp3"),
    ("Roblox bye", "Minecraft & Roblox", "roblox-bye.mp3"),
    ("Roblox hi", "Minecraft & Roblox", "roblox-hi-sound.mp3"),
    ("Old Minecraft zombie", "Minecraft & Roblox", "old-sound-of-zombie-in-minecraft.mp3"),
    ("Minecraft level up", "Minecraft & Roblox", "levelup.mp3"),
    ("Enderman teleport", "Minecraft & Roblox", "teleport1_Cw1ot9l.mp3"),
    ("Creeper explosion", "Minecraft & Roblox", "creeper-explosion.mp3"),
    ("Roblox sword", "Minecraft & Roblox", "roblox-sword.mp3"),
    ("Minecraft villager death", "Minecraft & Roblox", "villager.mp3"),
    ("Minecraft bow", "Minecraft & Roblox", "bow_shoot.mp3"),
    ("Creeper hiss", "Minecraft & Roblox", "creeper.mp3"),
    ("Minecraft eating", "Minecraft & Roblox", "nom-nom-nom_gPJiWn4.mp3"),
    ("TF2 critical hit", "Shooters", "critical-hit-sounds-effect.mp3"),
    ("TF2 frying pan", "Shooters", "melee_frying_pan_01.mp3"),
    ("M1 Garand ping", "Shooters", "ping_4TjeI1U.mp3"),
    ("Enemy AC-130 above", "Shooters", "enemy-ac130-above2.mp3"),
    ("Victory Royale (Fortnite)", "Shooters", "victory-royale.mp3"),
    ("Betrayal (Halo)", "Shooters", "betrayal_EKW4y6T.mp3"),
    ("Headshot", "Shooters", "headshot_1.mp3"),
    ("Let's do this! (COD4)", "Shooters", "lets-do-this.mp3"),
    ("Skill issue (Halo announcer)", "Shooters", "skill-issue-halo-announcer.mp3"),
    ("Flashbang (CS)", "Shooters", "flashbang-cs_qoRhxLn.mp3"),
    ("AWP shot (CS)", "Shooters", "awp_02.mp3"),
    ("Valorant kill", "Shooters", "multikill-1.mp3"),
    ("Half-Life crowbar", "Shooters", "half-life-crowbar.mp3"),
    ("OK, let's go (CS)", "Shooters", "counter-strike-jingle-cs-radio-ok-lets-go.mp3"),
    ("Fortnite chest", "Shooters", "fortnite.mp3"),
    ("Valorant ace", "Shooters", "valorant-ace-sound.mp3"),
    ("Enemy spotted", "Shooters", "counter-strike-jingle-cs-radio-enemy-spotted.mp3"),
    ("Falcon Punch!", "Fighting games", "falconpunch.swf.mp3"),
    ("Get over here! (Scorpion)", "Fighting games", "scorpion-get_over_here.mp3"),
    ("Round one, fight!", "Fighting games", "mortal-kombat-9-sound-drop-round-1-fight.mp3"),
    ("Perfect! (Street Fighter)", "Fighting games", "perfect-street-fighter-sound-effect.mp3"),
    ("Fatality (Mortal Kombat)", "Fighting games", "16_2.mp3"),
    ("K.O. (Street Fighter)", "Fighting games", "mlg-resource-street-fighter-ko-greenscreen.mp3"),
    ("Toasty! (Mortal Kombat)", "Fighting games", "toasty_tfCWsU6.mp3"),
    ("Round two (Mortal Kombat)", "Fighting games", "round-2-fight-mortal-kombat-sound-effect.mp3"),
    ("A new challenger approaches", "Fighting games",
     "challenger-approaching-super-smash-bros.mp3"),
    ("Hadouken!", "Fighting games", "hadouken.mp3"),
    ("Hog Rider", "Mobile games", "hog-rider.mp3"),
    ("Mega Knight (Clash Royale)", "Mobile games", "evolution-mega-knight.mp3"),
    ("Fire in the hole (Geometry Dash)", "Mobile games", "fire-in-the-hole-geometry-dash.mp3"),
    ("Among Us round start", "Mobile games", "among-us-roundstart.mp3"),
    ("Impostor kill (Among Us)", "Mobile games", "stationary-kill_gDwMUvN.mp3"),
    ("Clash Royale startup", "Mobile games", "clash-royale-start-up-sound.mp3"),
    ("Clash of Clans startup", "Mobile games", "clash_of_clan_start_up_soundmp3converter.mp3"),
    ("Dead body reported (Among Us)", "Mobile games",
     "among-us-dead-body-reported-sound-effect_BsczDVE.mp3"),
    ("Final Fantasy victory fanfare", "Classic games", "final-fantasy-vii-victory-fanfare-1.mp3"),
    ("Wololo (Age of Empires)", "Classic games", "sound-9.mp3"),
    ("Low honor (Red Dead 2)", "Classic games", "low-honor-rdr-2.mp3"),
    ("Sonic rings falling", "Classic games", "sonic-rings-drop.mp3"),
    ("GMod ragdoll", "Classic games", "tmpl0bxqky_.mp3"),
    ("Metal Gear codec", "Classic games", "codec.mp3"),
    ("PS2 startup", "Classic games", "ps2_start_up.mp3"),
    ("Dark Souls death", "Classic games", "dark-souls-you-died-sound-effect_hm5sYFG.mp3"),
    ("Mission passed (GTA San Andreas)", "Classic games",
     "gta-san-andreas-mission-complete-sound-hq.mp3"),
    ("Sonic spin dash", "Classic games", "sonic-spindash.mp3"),
    ("Sonic spring", "Classic games", "sonic-spring.mp3"),
    ("Game Boy startup", "Classic games", "nintendo-game-boy-startup.mp3"),
    ("Sonic jump", "Classic games", "jump.mp3"),
    ("GameCube startup", "Classic games", "gamecube-startup.mp3"),
    ("You're too slow! (Sonic)", "Classic games", "sonic-youre-too-slow.mp3"),
    ("Low health beep", "Classic games", "low-health-critical-health-pokemon.mp3"),
    ("Sans talking (Undertale)", "Indie games", "just-sans-talking.mp3"),
    ("Megalovania (Undertale)", "Indie games", "megalovania.mp3"),
    ("Pizza Tower taunt", "Indie games", "sfx_taunt.mp3"),
    ("Parry (Ultrakill)", "Indie games", "parry-ultrakill.mp3"),
    ("Happy Wheels victory", "Indie games", "victory_sJDDywi.mp3"),
    ("Gaster Blaster (Undertale)", "Indie games", "gaster_blaster_sound_effect_1.mp3"),
    ("Undertale damage", "Indie games", "undertale-damage-taken.mp3"),
]

# the tv & movie sounds pack, the same way (Myinstants' most-played)
_TV_MOVIES = [
    ("Jeopardy theme", "Game shows", "jeopardy-themelq.mp3"),
    ("Family Feud good answer", "Game shows", "family-feud-good-answer.mp3"),
    ("Curb Your Enthusiasm", "TV themes", "curb-your-enthusiasm.mp3"),
    ("Imperial March", "Star Wars", "imperial_march.mp3"),
    ("D'oh! (Homer)", "Cartoons", "doh.swf.mp3"),
    ("2000 years later (SpongeBob)", "Cartoons",
     "spongebob-2000-years-later-2019-download-link.mp3"),
    ("Correct answer (game show)", "Game shows", "correct.mp3"),
    ("Final Jeopardy thinking music", "Game shows", "jeopardy-final-jeopardy-thinking-music.mp3"),
    ("Jeopardy correct answer", "Game shows", "rightanswer.mp3"),
    ("Jeopardy Daily Double", "Game shows",
     "jeopardy-daily-double-sound-effect-from-youtube_76mCCAq.mp3"),
    ("Family Feud wrong answer", "Game shows", "neg-portal2buzzer_2DIuFda.mp3"),
    ("Wrong answer (game show)", "Game shows", "wrong_5.mp3"),
    ("America's Got Talent buzzer", "Game shows", "y2mate_eb8vm6J.mp3"),
    ("Seinfeld theme", "TV themes", "seinfeld-theme_1.mp3"),
    ("The X-Files theme", "TV themes", "expedientes-secretos-x-musica22.mp3"),
    ("Better Call Saul", "TV themes", "saul-goodman-better-call-saul.mp3"),
    ("Breaking Bad intro", "TV themes", "breaking-bad-intro.mp3"),
    ("Stranger Things clock", "TV themes", "stranger-things-clock-sound.mp3"),
    ("Breaking news intro", "TV themes", "news_intro-maximilien_-1801238420_2.mp3"),
    ("The more you know", "TV themes", "the-more-you-know.mp3"),
    ("Hell's Kitchen dramatic", "TV themes", "hells-kitchen-sfx.mp3"),
    ("Huh? (Home Improvement)", "TV themes", "home-improvement-huh.mp3"),
    ("Are you sure? (Omni-Man)", "TV themes", "omni-man-are-you-sure.mp3"),
    ("Homelander angry violin", "TV themes", "homelander-going-crazy-angry-violin-theme-song.mp3"),
    ("iCarly cheers", "TV themes", "icarly-cheers.mp3"),
    ("Netflix intro", "Movies", "nouveau-jingle-netflix.mp3"),
    ("THX", "Movies", "thx.mp3"),
    ("Jaws theme", "Movies", "jaws-theme_TDORPKA.mp3"),
    ("Mission: Impossible", "Movies", "m3.mp3"),
    ("Pirates of the Caribbean", "Movies", "pirates-mp3cut_xxOvJfH.mp3"),
    ("The Good, the Bad and the Ugly whistle", "Movies", "goodbadugly-whistle-long.mp3"),
    ("Pink Panther", "Movies", "the-pink-panther-theme-song-original-version.mp3"),
    ("Yakety Sax", "Movies", "yakety-sax-music.mp3"),
    ("It was at this moment he knew", "Movies", "heknew.mp3"),
    ("I'm Batman", "Movies", "im-batman.mp3"),
    ("Batman transition", "Movies", "batman-transition-download-sound-link.mp3"),
    ("You shall not pass!", "Movies", "gandalf_shallnotpass.mp3"),
    ("Avengers theme", "Movies", "avengers_.mp3"),
    ("Good morning, Vietnam!", "Movies", "goodmorn1.mp3"),
    ("Mine! Mine! (Finding Nemo)", "Movies", "mine-mine_Z6BwRzI.mp3"),
    ("Lightsaber on", "Star Wars", "lightsaber_02.mp3"),
    ("Roger, roger", "Star Wars", "star-wars-b1-battle-droid_kampfdroide-roger-roger-sound.mp3"),
    ("R2-D2 scream", "Star Wars", "r2d2_scream_converted.mp3"),
    ("Darth Vader breathing", "Star Wars", "darth-vader.mp3"),
    ("Cantina band", "Star Wars", "cantina-band.mp3"),
    ("SpongeBob disappointed", "Cartoons", "spongebob-disappointed-sound-effect.mp3"),
    ("Victory screech (SpongeBob)", "Cartoons", "victoryscreech.mp3"),
    ("Oh yeah (Mr. Krabs)", "Cartoons", "mr-krabs.mp3"),
    ("SpongeBob foghorn", "Cartoons", "spongebob-fog-horn.mp3"),
    ("SpongeBob sad song", "Cartoons", "spongebob-sad-song.mp3"),
    ("Hi, how are ya? (SpongeBob)", "Cartoons", "spongebob-hi-how-are-ya-.mp3"),
    ("Grass skirt chase", "Cartoons", "spongebob-music_-grass-skirt-chase-1.mp3"),
    ("One eternity later", "Cartoons", "one-eternity-later.mp3"),
    ("Two hours later", "Cartoons", "spongebob-two-hours-later-2019-download-link.mp3"),
    ("One hour later", "Cartoons", "one-hour-later-spongebob-time-card-96.mp3"),
    ("I'm SpongeBob", "Cartoons", "im-spongebob.mp3"),
    ("My leg! (SpongeBob)", "Cartoons", "my-leg_gtcfNMu.mp3"),
    ("I'm ready! (SpongeBob)", "Cartoons", "im-ready.mp3"),
    ("No, this is Patrick!", "Cartoons", "no-this-is-patrick.mp3"),
    ("Patrick screaming", "Cartoons", "patrick_GojJ8l0.mp3"),
    ("Homer scream", "Cartoons", "tmp90lreogl.mp3"),
    ("Peter Griffin laugh", "Cartoons", "laugh-3_9wVKqU7.mp3"),
    ("Timmy! (South Park)", "Cartoons", "timmy.mp3"),
    ("Tom scream (Tom and Jerry)", "Cartoons", "toms-screams.mp3"),
    ("Woody Woodpecker laugh", "Cartoons", "woody-woodpecker-laugh.mp3"),
    ("Ed, Edd n Eddy", "Cartoons", "ed-edd-n-eddy-subaluwa-full-best-version_z4mgiJw.mp3"),
    ("Charlie Brown teacher", "Cartoons", "wha-wha1.mp3"),
    ("Shut up and take my money", "Cartoons", "shut-up_2.mp3"),
    ("Baja Blast (Hank Hill)", "Cartoons", "hank-hill-baja-blast.mp3"),
    ("Donnie (Wild Thornberrys)", "Cartoons", "media_va1VnYo.mp3"),
    ("My mom! (Muscle Man)", "Cartoons", "my-mom.mp3"),
]

# the anime sounds pack, the same way (Myinstants' most-played)
_ANIME = [
    ("Kamehameha!", "Dragon Ball", "kamehameha.swf.mp3"),
    ("Domain expansion (Gojo)", "Jujutsu Kaisen", "rpreplay_final1623689697_mov.mp3"),
    ("WRYYY", "JoJo", "dio-wryyy.mp3"),
    ("Sharingan", "Naruto & One Piece", "collen-eyes-efect.mp3"),
    ("Explosion! (Megumin)", "More anime", "explosion_3.mp3"),
    ("Ultra Instinct", "Dragon Ball", "ultra-instinct-theme-official-version.mp3"),
    ("Super Saiyan aura", "Dragon Ball", "saiyan.mp3"),
    ("Something just snapped (Vegeta)", "Dragon Ball", "vegeta-something-just-snapped_s9osoEc.mp3"),
    ("Hey, it's me, Goku!", "Dragon Ball", "hey-its-me-goku.mp3"),
    ("Instant transmission", "Dragon Ball", "tmpubima4i9.mp3"),
    ("I'm very angry (Goku)", "Dragon Ball", "im-very-angry-goku.mp3"),
    ("Heavy punch (DBZ)", "Dragon Ball", "dragon-ball-z-heavy-punch.mp3"),
    ("Piccolo aura", "Dragon Ball", "piccolo-aura.mp3"),
    ("Goku teleport", "Dragon Ball", "goku-teleport-sound.mp3"),
    ("Ayayay (JoJo)", "JoJo", "jojos-bizarre-adventure-ay-ay-ay-ay-_-sound-effect.mp3"),
    ("Oh no! (JoJo)", "JoJo", "oh-no_7.mp3"),
    ("Yes yes yes YES (JoJo)", "JoJo", "yes-yes-yes-yes-yes.mp3"),
    ("Time stop (DIO)", "JoJo", "dio-time-stop.mp3"),
    ("Pillar Men awaken", "JoJo", "jjba-pillar-men2.mp3"),
    ("Naruto sad song", "Naruto & One Piece", "naruto-sad-music-instant.mp3"),
    ("Jutsu activation", "Naruto & One Piece", "katon.mp3"),
    ("Shadow clone (Naruto)", "Naruto & One Piece", "export_ofoct_uz3AV4x.mp3"),
    ("Can we get much higher (One Piece)", "Naruto & One Piece",
     "can-we-get-much-higher-one-piece-meme.mp3"),
    ("Zehahaha (Blackbeard)", "Naruto & One Piece", "zehahaha_laugh.mp3"),
    ("One Piece intro", "Naruto & One Piece", "one-piece-intro.mp3"),
    ("Domain expansion (Sukuna)", "Jujutsu Kaisen", "domain-expansion-sukuna.mp3"),
    ("Sukuna laugh", "Jujutsu Kaisen", "sukuna-laugh.mp3"),
    ("Hollow Purple", "Jujutsu Kaisen", "hollow-purple.mp3"),
    ("Yowai mo!", "Jujutsu Kaisen", "yowai-mo.mp3"),
    ("You crying? (Gojo)", "Jujutsu Kaisen", "you-crying-gojo.mp3"),
    ("Return by Death (Re:Zero)", "More anime", "re-zero-return-by-death.mp3"),
    ("Wow! (Fairy Tail)", "More anime", "wow_2.mp3"),
    ("L's theme (Death Note)", "More anime", "00000000000000000.mp3"),
    ("Death Note confusion", "More anime", "death-note-confusion-sound.mp3"),
    ("Attack on Titan", "More anime", "shingeki-no-kyojin-ost-attack-on-titan2.mp3"),
    ("Anime punch", "Anime sounds", "strongpunch.mp3"),
    ("Nani? (manga)", "Anime sounds", "tmph3o88c10.mp3"),
    ("Anime pop", "Anime sounds", "anime-pop-sfx.mp3"),
]

# the sports & hype pack, the same way (Myinstants' most-played)
_SPORTS = [
    ("Crowd cheering", "Crowd", "cheering.mp3"),
    ("Let's get ready to rumble!", "Announcers", "lets-get-ready-to-rumble.mp3"),
    ("Boxing bell", "Bells & horns", "boxing-bell.mp3"),
    ("John Cena entrance", "Wrestling", "cena.mp3"),
    ("Siuuu (Ronaldo)", "Players", "ronaldo-siuuuu.mp3"),
    ("NBA horn", "Bells & horns", "nba-horn-sfx.mp3"),
    ("Applause", "Crowd", "applause-4.mp3"),
    ("Booing", "Crowd", "booing.mp3"),
    ("Crowd booing", "Crowd", "crowd-boo-sound-effect.mp3"),
    ("Golf clap", "Crowd", "golfclap.mp3"),
    ("Crowd clap", "Crowd", "applause_2.mp3"),
    ("Girls cheering", "Crowd", "cheering-indoor_gen-hdf-07357.mp3"),
    ("Defense! (NBA)", "Crowd", "defense-chant.mp3"),
    ("It's time! (Bruce Buffer)", "Announcers", "bruce-buffer-its-time.mp3"),
    ("Bang! (Mike Breen)", "Announcers", "mike-breen-bang-bang.mp3"),
    ("Wrestling bell", "Bells & horns", "campana.mp3"),
    ("WWE ring bell", "Bells & horns", "wwe-bell.mp3"),
    ("Vikings horn", "Bells & horns", "vikinghorn.mp3"),
    ("Coach whistle", "Bells & horns", "whistle_BBvcaZ1.mp3"),
    ("Take your marks beep", "Bells & horns", "take-your-marks-beep.mp3"),
    ("Basketball swish", "Bells & horns", "basketball-swish_OMsr9CN.mp3"),
    ("NFL theme", "Themes", "nfl-theme-song-hq-mp3cut_yjEDUm1.mp3"),
    ("NFL Draft chime", "Themes", "nfl-draft-chime.mp3"),
    ("Sunday Night Football theme", "Themes",
     "nbc-nfl-sunday-night-football-theme-music_alMduUF.mp3"),
    ("ESPN NFL theme", "Themes", "espn-nfl-theme.mp3"),
    ("NFL on CBS theme", "Themes", "nfl-on-cbs-theme-song.mp3"),
    ("NFL on Fox", "Themes", "nfl-on-fox-theme-music.mp3"),
    ("SportsCenter Top 10", "Themes", "sportscenter-top-10.mp3"),
    ("We Are the Champions", "Themes", "we-are-the-champions-copia.mp3"),
    ("And his name is John Cena", "Wrestling", "hello-its-john-cena.mp3"),
    ("Wooo! (Ric Flair)", "Wrestling", "woo.mp3"),
    ("Oh yeah! (Macho Man)", "Wrestling", "oh-yeah-macho-man-randy-savage_LY3mBNt.mp3"),
    ("Watch out, Randy Orton", "Wrestling", "randyortonrko-soundeffect.mp3"),
    ("Time to play the game (Triple H)", "Wrestling", "triple-h-time-to-play-the-game.mp3"),
    ("The Undertaker", "Wrestling", "the-undertaker-wwe.mp3"),
    ("Kobe!", "Players", "kobe.mp3"),
    ("LeBron!", "Players", "lebron.mp3"),
    ("Tu tu tu du, Max Verstappen", "Players", "tu-tu-tu-du-max-verstappen.mp3"),
    ("Box, box (F1 radio)", "Players", "formula-1-box-box.mp3"),
    ("You know who I am (Kevin Durant)", "Players", "you-know-who-i-am-kevin-durant.mp3"),
]

BUILT_IN = [{
    "id": "memes",
    "name": "Meme sounds",
    "description": "The 104 most-played meme sounds of the last 16 years: vine boom, bruh, "
                   "anime wow, MLG air horn, emotional damage, metal pipe, sad violin, Roblox "
                   "oof, Taco Bell bong, Windows XP error, Leeroy Jenkins and many more.",
    "license": "As on Myinstants",
    "author": "Onion Board",
    "emoji": "😂",
    "tags": ["Memes"],
    "categories": ["Reactions", "Gaming", "Fails", "Vine & TikTok", "Classic memes", "Music"],
    "links": [{"name": n, "category": c,
               "url": f"https://www.myinstants.com/media/sounds/{f}"}
              for n, c, f in _MEMES],
}, {
    "id": "gaming",
    "name": "Gaming sounds",
    "description": "The 110 most-played video game sounds: Mario coin and 1-up, Zelda chest, "
                   "Pokemon level up, Minecraft XP and creeper, Among Us emergency meeting, "
                   "Finish him!, bomb has been planted, Victory Royale and many more.",
    "license": "As on Myinstants",
    "author": "Onion Board",
    "emoji": "🎮",
    "tags": ["Gaming"],
    "categories": ["Nintendo", "Minecraft & Roblox", "Shooters", "Fighting games",
                   "Mobile games", "Classic games", "Indie games"],
    "links": [{"name": n, "category": c,
               "url": f"https://www.myinstants.com/media/sounds/{f}"}
              for n, c, f in _GAMING],
}, {
    "id": "tv-movies",
    "name": "TV & movie sounds",
    "description": "The 71 most-played TV and film sounds: Jeopardy and Family Feud, Curb Your "
                   "Enthusiasm, the X-Files, Jaws, Mission: Impossible, Star Wars, SpongeBob, "
                   "the Simpsons and many more.",
    "license": "As on Myinstants",
    "author": "Onion Board",
    "emoji": "🎬",
    "tags": ["TV & movies"],
    "categories": ["Game shows", "TV themes", "Movies", "Star Wars", "Cartoons"],
    "links": [{"name": n, "category": c,
               "url": f"https://www.myinstants.com/media/sounds/{f}"}
              for n, c, f in _TV_MOVIES],
}, {
    "id": "anime",
    "name": "Anime sounds",
    "description": "The 38 most-played anime sounds: Kamehameha, Ultra Instinct, JoJo's WRYYY "
                   "and time stop, Naruto, One Piece, Gojo's and Sukuna's domain expansions, "
                   "Megumin's explosion and more.",
    "license": "As on Myinstants",
    "author": "Onion Board",
    "emoji": "🍥",
    "tags": ["Anime"],
    "categories": ["Dragon Ball", "JoJo", "Naruto & One Piece", "Jujutsu Kaisen",
                   "More anime", "Anime sounds"],
    "links": [{"name": n, "category": c,
               "url": f"https://www.myinstants.com/media/sounds/{f}"}
              for n, c, f in _ANIME],
}, {
    "id": "sports",
    "name": "Sports & hype",
    "description": "The 40 most-played sports sounds: crowd cheers and boos, Let's get ready to "
                   "rumble, boxing and wrestling bells, NBA and NFL horns and themes, John Cena, "
                   "Ric Flair, Siuuu and more.",
    "license": "As on Myinstants",
    "author": "Onion Board",
    "emoji": "📣",
    "tags": ["Sports"],
    "categories": ["Crowd", "Announcers", "Bells & horns", "Themes", "Wrestling", "Players"],
    "links": [{"name": n, "category": c,
               "url": f"https://www.myinstants.com/media/sounds/{f}"}
              for n, c, f in _SPORTS],
}, {
    "id": "streamer",
    "name": "Streamer pack",
    "description": "For live streams: starting soon, just chatting, BRB and ending music; "
                   "follower, sub, donation and raid alerts; air horn, cheers, fails (bonk, "
                   "buzzer, sad trombone), chat reactions, a 3-2-1 Go announcer and transitions. "
                   "Ctrl+Alt+3 air horn, Ctrl+Alt+4 bonk.",
    "url": f"{updates.DOWNLOADS}streamer-pack-1/onion-board-streamer-pack.zip",
    "sha256": "bb6b6895c3ef30f14e5a45a1b0cfc384de4691d960e1fdf1b0eae8967e1b638c",
    "size": 18299334,
    "sounds": 57,
    "license": "CC0",
    "author": "Onion Board",
    "emoji": "📺",
    "tags": ["Streaming"],
    "preview": {"url": f"{updates.DOWNLOADS}streamer-pack-1/streamer-preview.zip",
                "sha256": "4baeb7fe3d9bdbd2a07db071ba89666d9b3a910118cb510325c1adef1478191c",
                "size": 376595},
    "categories": ["Stream music", "Alerts", "Hype", "Fails", "Chat reactions", "Announcer",
                   "Transitions"],
}, {
    "id": "esports",
    "name": "Esports pack",
    "description": "For streams, casting, LAN parties and voice chat: arena crowd cheers and "
                   "boos, air horn, a fighting-game announcer (3, 2, 1, Fight!, Multi kill, "
                   "Flawless victory), shooter callouts, plays and memes. Hype music loops; "
                   "Ctrl+Alt+1 hype music, Ctrl+Alt+3 the countdown.",
    "url": f"{updates.DOWNLOADS}esports-pack-1/onion-board-esports-pack.zip",
    "sha256": "661dee49cef5796519fb95bd16ce21283bdfae955ca6fbe973c7b35943791ba5",
    "size": 18546197,
    "sounds": 51,
    "license": "CC0",
    "author": "Onion Board",
    "emoji": "🏆",
    "tags": ["Gaming", "Streaming"],
    "preview": {"url": f"{updates.DOWNLOADS}esports-pack-1/esports-preview.zip",
                "sha256": "81553c247a987ef7dabe7da2b8b4a4555e5fe7e09a9c73f7dd063c491cd8ea4b",
                "size": 407620},
    "categories": ["Hype music", "Crowd", "Announcer", "Callouts", "Plays", "Memes"],
}, {
    "id": "general",
    "name": "General sound pack",
    "description": "483 sounds for everything, in 20 categories: memes (air horn, boom, bruh), "
                   "comedy, game show buzzers, crowds, people, 25 animals, video game blips and "
                   "power-ups, notifications, combat, impacts, whooshes, sci-fi, magic, horror, "
                   "vehicles, household, nature ambiences, sports, music stings and party sounds.",
    "url": f"{updates.DOWNLOADS}general-pack-1/onion-board-general-pack.zip",
    "sha256": "9044bdf70427ef854e7c1ec698901bc9f8a7f59c23ade1af55a046573db57c58",
    "size": 44324802,
    "sounds": 483,
    "license": "CC0",
    "author": "Onion Board",
    "emoji": "🔊",
    "tags": ["Everyday", "Memes"],
    "preview": {"url": f"{updates.DOWNLOADS}general-pack-1/general-preview.zip",
                "sha256": "18a6154703c5a96e868e2b74d0e38ddb4c34cd8deffeddc39f64bbb116312985",
                "size": 356511},
    "categories": ["Memes", "Comedy", "Game show", "Crowd", "People", "Animals", "Video game",
                   "Notifications", "Combat", "Impacts", "Transitions", "Sci-fi", "Magic", "Horror",
                   "Vehicles", "Household", "Nature", "Sports", "Music", "Party"],
}, {
    "id": "podcast",
    "name": "Podcast pack",
    "description": "For podcasts, talk streams and live shows: intro, outro and background "
                   "music, stingers, ba-dum-tss, bleep, audience laughs and applause, comedy "
                   "sounds, game-show buzzers and studio sounds (phone, doorbell, "
                   "typewriter).",
    "url": f"{updates.DOWNLOADS}podcast-pack-1/onion-board-podcast-pack.zip",
    "sha256": "c560b16bb4f87120394ff43986645119bb7a7071c54d6ceb256a4def3bae69d9",
    "size": 15628205,
    "sounds": 51,
    "license": "CC0 (applause public domain)",
    "author": "Onion Board",
    "emoji": "🎙️",
    "tags": ["Podcast"],
    "preview": {"url": f"{updates.DOWNLOADS}podcast-pack-1/podcast-preview.zip",
                "sha256": "1a427fc256d0152b7e5d2250337971e2660595dad21b7afd5b2f8184f7af4db1",
                "size": 392570},
    "categories": ["Show music", "Stingers", "Reactions", "Comedy", "Game show", "Studio"],
}, {
    "id": "halloween",
    "name": "Halloween pack",
    "description": "For Halloween parties, horror streams and pranks: screams, evil laughs and "
                   "witch cackles, zombies and monster roars, jump scares, creaky doors, a clock "
                   "striking midnight, thunder, wolves and owls. Spooky music loops; Ctrl+Alt+2 a "
                   "scream, Ctrl+Alt+4 a jump scare.",
    "url": f"{updates.DOWNLOADS}halloween-pack-1/onion-board-halloween-pack.zip",
    "sha256": "9ac377385e2979396b132fae75ae874b39559c4b4deb7bfb38a77e3d6a6c0f9d",
    "size": 26947272,
    "sounds": 49,
    "license": "CC0 + CC BY (credits inside)",
    "author": "Onion Board",
    "emoji": "🎃",
    "tags": ["Spooky"],
    "preview": {"url": f"{updates.DOWNLOADS}halloween-pack-1/halloween-preview.zip",
                "sha256": "8014fbf24322b467e09e4a4eaff179aa974f424750d0191393655fe27ae5a090",
                "size": 480541},
    "categories": ["Spooky music", "Screams", "Monsters", "Jump scares", "Haunted house",
                   "Night"],
}, {
    "id": "gm-starter",
    "name": "GM starter pack",
    "description": "For tabletop games (D&D and friends): tavern, travel, weather, "
                   "dungeon, combat, magic, boss and ending sounds. Music loops, and "
                   "Ctrl+Alt+1/2/3 switch tavern, battle and boss music.",
    "url": f"{updates.DOWNLOADS}gm-pack-1/onion-board-gm-starter-pack.zip",
    "sha256": "bfb53856bb8f225f336e5391b9ceb0773da2bca61923de0102abf888d499f09d",
    "size": 28480681,
    "sounds": 67,
    "license": "CC0 + CC BY (credits inside)",
    "author": "Onion Board",
    "emoji": "🎲",
    "tags": ["Tabletop", "Music"],
    "preview": {"url": f"{updates.DOWNLOADS}gm-pack-1/gm-starter-preview.zip",
                "sha256": "287c97df2e05a8b0aefb76381ab8bc91f28546caa0b2a1dbd8e5228b71d611db",
                "size": 523245},
    "categories": ["Tavern", "Travel", "Weather", "Dungeon", "Combat", "Magic", "Boss",
                   "Endings"],
}]


def parse(raw) -> list[Pack]:
    """The packs in a catalog (its "packs" list, or a bare list): any entry that isn't a
    pack on the project's own releases, with a checksum and a sane size, is left out."""
    items = raw.get("packs") if isinstance(raw, dict) else raw
    out, seen = [], set()
    for d in items if isinstance(items, list) else []:
        try:
            links = _links(d.get("links"))
            p = Pack(id=str(d["id"]), name=str(d["name"]).strip(),
                     description=str(d.get("description") or "").strip(),
                     url="" if links else str(d["url"]),
                     sha256="" if links else str(d["sha256"]).lower(),
                     size=int(d.get("size") or 0), sounds=int(d.get("sounds") or 0),
                     license=str(d.get("license") or "CC0").strip(),
                     author=str(d.get("author") or "").strip(),
                     emoji=str(d.get("emoji") or "📦")[:4],
                     categories=[str(c) for c in d.get("categories") or []
                                 if isinstance(c, str)][:20],
                     tags=[t.strip()[:24] for t in d.get("tags") or []
                           if isinstance(t, str) and t.strip()][:4],
                     links=links)
        except (KeyError, TypeError, ValueError, AttributeError):
            log.debug("skipped a catalog entry: %r", d)
            continue
        if (not ID_RE.fullmatch(p.id) or p.id in seen or not p.name
                or not (p.links or (p.url.startswith(updates.DOWNLOADS)
                                    and updates.SHA_RE.fullmatch(p.sha256)))
                or not 0 <= p.size <= MAX_SIZE):
            log.debug("skipped catalog entry %r", p.id)
            continue
        seen.add(p.id)
        if p.links:
            p.sounds = len(p.links)
            p.categories = p.categories or list(dict.fromkeys(
                k.category for k in p.links if k.category))[:20]
        p.preview_url, p.preview_sha256, p.preview_size = _preview(d.get("preview"))
        out.append(p)
    return out


def _preview(d) -> tuple[str, str, int]:
    """A catalog entry's "preview" ({url, sha256, size}), or nothing when it isn't one
    on our releases with a checksum (the pack itself still shows)."""
    try:
        url, sha, size = str(d["url"]), str(d["sha256"]).lower(), int(d.get("size") or 0)
    except (KeyError, TypeError, ValueError):
        return "", "", 0
    if (not url.startswith(updates.DOWNLOADS) or not updates.SHA_RE.fullmatch(sha)
            or not 0 <= size <= PREVIEW_MAX):
        return "", "", 0
    return url, sha, size


def built_in() -> list[Pack]:
    return parse(BUILT_IN)


_listed: dict[str, Pack] = {}   # every pack the online list has had, by id


def known(pack_id: str) -> Pack | None:
    """A free pack: from the online list once it was read (a pack added since this
    version was built), else this version's own; None when neither has it."""
    return _listed.get(pack_id) or next((p for p in built_in() if p.id == pack_id), None)


def name_of(pack_id: str) -> str:
    """A free pack's name ("Streamer pack"), or ""."""
    p = known(pack_id)
    return p.name if p else ""


def catalog() -> list[Pack]:
    """The packs on offer now, from the project's list. Raises (net.ProxyError when
    switched off or Offline, OSError / ValueError when it can't be read): the caller
    shows built_in() and says why. Call off the UI thread."""
    netlog.cause(FEATURE, "You opened Free packs: reading the list of packs")
    req = urllib.request.Request(CATALOG_URL, headers={"User-Agent": "OnionBoard (sound packs)"})
    with net.urlopen(req, timeout=15, feature=FEATURE) as r:
        packs = parse(json.loads(r.read(CATALOG_LIMIT).decode("utf-8")))
    if not packs:
        raise ValueError("the pack list is empty")
    _listed.update((p.id, p) for p in packs)
    return packs


def download(pack: Pack, progress: Callable[[int, int], object] | None = None,
             cancelled: Callable[[], bool] | None = None) -> Path:
    """Fetch `pack` into the app folder's "packs", checked against its SHA-256; its
    path. Raises updates.UpdateError with a message for the user. Call off the UI
    thread. A links pack: download_links (this gives just its path)."""
    if pack.links:
        return download_links(pack, progress, cancelled)[0]
    kept = backup.kept_free_pack(pack.id)
    if kept is not None and updates._sha256(kept) == pack.sha256:
        return kept   # added before and still kept: the same file, not fetched again
    netlog.cause(FEATURE, f"You pressed Add on the {netlog.quoted(pack.name)} pack")
    path = updates.fetch(pack.url, pack.sha256, pack.path, (updates.DOWNLOADS,), MAX_SIZE,
                         "pack", pack.size, progress, cancelled, feature=FEATURE)
    try:   # its checksum matched a broken upload: kept, it would read "Add again"
        with zipfile.ZipFile(path) as z:
            bad = z.testzip()
    except (OSError, zipfile.BadZipFile, EOFError) as e:
        bad = str(e) or "unreadable"
    if bad is not None:
        log.warning("pack %s: the downloaded zip is damaged (%s)", pack.id, bad)
        path.unlink(missing_ok=True)
        raise updates.UpdateError(_("the pack's file is damaged, so it wasn't kept"))
    return path


def _sleep(seconds: float, cancelled: Callable[[], bool] | None = None):
    """Wait `seconds`, or less once `cancelled` says so."""
    end = time.monotonic() + seconds
    while (left := end - time.monotonic()) > 0:
        if cancelled is not None and cancelled():
            return
        time.sleep(min(left, 0.25))


class _Pace:
    """Spaces a links pack's downloads out: one starts every LINK_GAP seconds at most,
    and after Myinstants says "too many requests" every link waits as long as it asked."""

    def __init__(self, cancelled: Callable[[], bool] | None = None):
        self.lock = threading.Lock()
        self.cancelled = cancelled
        self.next = 0.0              # the earliest the next link may start
        self.refused: list[Exception] = []   # links refused for good: "too many requests"

    def wait(self):
        while not (self.cancelled is not None and self.cancelled()):
            with self.lock:
                left = self.next - time.monotonic()
                if left <= 0:   # (a hold() while this one waited moved it on)
                    self.next = time.monotonic() + LINK_GAP
                    return
            _sleep(left, self.cancelled)

    def hold(self, seconds: float):
        """No link starts for `seconds`: the site asked to slow down."""
        with self.lock:
            self.next = max(self.next, time.monotonic() + seconds)


def _try_again(e: Exception) -> tuple[float, bool] | None:
    """A failed link worth another try: (the least wait the site asked for, whether it
    said "too many requests"). None when it isn't: gone, not a sound, switched off,
    turned away over Tor."""
    from soundboard.online.ytsites import SwitchedOff, TorBlocked
    if isinstance(e, (SwitchedOff, TorBlocked)):
        return None
    cause = e.__cause__ or e.__context__
    if isinstance(cause, urllib.error.HTTPError):
        if cause.code == 429:
            try:
                asked = float(cause.headers.get("Retry-After") or 0)
            except (TypeError, ValueError):   # a date, or nonsense: our own waits
                asked = 0.0
            return min(max(asked, 0.0), LINK_MAX_WAIT), True
        return (0.0, False) if cause.code >= 500 else None
    if isinstance(cause, (urllib.error.URLError, TimeoutError, ConnectionError)):
        return 0.0, False
    return None


def _fetch_link(link: Link, dest: Path, pace: _Pace,
                cancelled: Callable[[], bool] | None = None) -> Path:
    """One link's MP3 into `dest`, when `pace` lets it start. A failure for now (a dropped
    connection, a busy server, "too many requests") gets up to len(LINK_RETRY_WAITS)
    more tries, each after a longer wait; after LINK_GIVE_UP links were refused for
    good the rest aren't asked for at all."""
    from soundboard.online import ytdl
    tries = len(LINK_RETRY_WAITS)
    for attempt in range(tries + 1):
        if len(pace.refused) >= LINK_GIVE_UP:
            raise pace.refused[0]
        pace.wait()
        if cancelled is not None and cancelled():
            raise updates.UpdateError(_("Stopped."))
        try:
            return Path(ytdl.download_audio(link.url, dest, thumbnail=False)[0])
        except Exception as e:  # noqa: BLE001 - sorted below: tried again or given up
            again = _try_again(e)
            if again is None:
                raise
            asked, busy = again
            if attempt == tries:
                if busy:
                    with pace.lock:
                        pace.refused.append(e)
                raise
            wait = max(LINK_RETRY_WAITS[attempt], asked)
            if busy:
                pace.hold(wait)   # every link waits, not just this one
            log.info("pack link %s failed (%s): trying again in %s s", link.url, e, wait)
            _sleep(wait, cancelled)
    raise AssertionError("every try returns or raises")


def download_links(pack: Pack, progress: Callable[[int, int], object] | None = None,
                   cancelled: Callable[[], bool] | None = None) -> tuple[Path, int]:
    """A links pack: each link fetched from Myinstants (LINK_WORKERS at once), then put
    in a zip of the backup format at pack.path, so it's added, kept, reset and removed
    like any other pack. (its path, how many links were skipped: gone, or not a sound).
    `progress` gets (links done, links). Raises updates.UpdateError when none came or
    it was cancelled. Call off the UI thread."""
    kept = backup.kept_free_pack(pack.id)
    if kept is not None:
        return kept, 0   # added before and still kept: not fetched again
    from concurrent.futures import ThreadPoolExecutor

    from soundboard.online.ytsites import temp_folder
    netlog.cause(FEATURE, f"You pressed Add on the {netlog.quoted(pack.name)} pack: its "
                          f"sounds, from Myinstants")
    tmp = temp_folder("sb-linkpack-")
    got: dict[int, Path] = {}
    errs: list[str] = []
    lock = threading.Lock()
    done = 0

    pace = _Pace(cancelled)

    def one(i: int, link: Link):
        nonlocal done
        if cancelled is not None and cancelled():
            return
        try:
            path = _fetch_link(link, tmp / str(i), pace, cancelled)
        except Exception as e:  # noqa: BLE001 - gone, offline, switched off: skipped
            log.info("pack %s: skipped %s (%s)", pack.id, link.url, e)
            with lock:
                errs.append(errors.plain(e))
        else:
            with lock:
                got[i] = Path(path)
        with lock:
            done += 1
            n = done
        if progress is not None:
            progress(n, len(pack.links))

    try:
        for i in range(len(pack.links)):
            (tmp / str(i)).mkdir()
        with ThreadPoolExecutor(LINK_WORKERS, thread_name_prefix="pack-link") as pool:
            list(pool.map(lambda a: one(*a), enumerate(pack.links)))
        if cancelled is not None and cancelled():
            raise updates.UpdateError(_("Stopped."))
        if not got:
            raise updates.UpdateError(errs[0] if errs else _("None of its sounds could be "
                                                              "downloaded."))
        _zip_links(pack, got, pack.path)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return pack.path, len(pack.links) - len(got)


def _zip_links(pack: Pack, got: dict[int, Path], dest: Path):
    """The fetched sounds as a pack zip (docs/BACKUP-FORMAT.md), in the list's order."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    order = sorted(got)
    folders = []
    try:
        with zipfile.ZipFile(part, "w", zipfile.ZIP_STORED) as z:   # MP3s don't shrink
            for n, i in enumerate(order, 1):
                link, audio = pack.links[i], got[i]
                folder = f"sounds/{n:03d}"
                entry: dict = {"name": link.name, "audio": audio.name}
                if link.category:
                    entry["tags"] = [link.category]
                z.write(audio, f"{folder}/{audio.name}")
                z.writestr(f"{folder}/sound.json", json.dumps(entry, ensure_ascii=False))
                folders.append(folder)
            z.writestr("onionboard.json", json.dumps({
                "format": "onionboard-board", "format_version": 1,
                "categories": list(dict.fromkeys(pack.links[i].category for i in order
                                                 if pack.links[i].category)),
                "sounds": folders, "settings": None}, ensure_ascii=False))
        part.replace(dest)
    except BaseException:
        part.unlink(missing_ok=True)
        raise


@dataclass
class Sample:
    """One of a preview's sounds: its name, its tile picture (PNG / JPEG bytes, or
    b"") and its audio file, unpacked."""
    name: str
    picture: bytes
    audio: Path


_sample_locks: dict[str, threading.Lock] = {}
_sample_locks_lock = threading.Lock()


def previews_dir() -> Path:
    return library.APP_DIR / "packs" / "previews"


def samples(pack: Pack, cancelled: Callable[[], bool] | None = None) -> list[Sample]:
    """A few of `pack`'s sounds to try before adding it: its preview fetched (once,
    checked against its SHA-256) and unpacked. [] when it has none. Raises
    updates.UpdateError (switched off, offline, a bad file). Call off the UI thread.
    A links pack's are its first SAMPLES links, fetched from Myinstants (_link_samples)."""
    if not pack.preview_url and not pack.links:
        return []
    with _sample_locks_lock:
        lock = _sample_locks.setdefault(pack.id, threading.Lock())
    with lock:   # two at once wrote the same .part file: a bad checksum, no samples
        return _link_samples(pack, cancelled) if pack.links else _samples(pack, cancelled)


def _link_samples(pack: Pack, cancelled: Callable[[], bool] | None) -> list[Sample]:
    """A links pack's first SAMPLES sounds, each fetched once (then kept with the other
    previews, under its own name: the list changing fetches only what's new)."""
    from soundboard.online.ytsites import temp_folder
    d = previews_dir() / f"{pack.id}-links"
    pace = _Pace(cancelled)
    d.mkdir(parents=True, exist_ok=True)
    found, errs = [], []
    told = False
    for link in pack.links[:SAMPLES]:
        if cancelled is not None and cancelled():
            raise updates.UpdateError(_("Stopped."))
        kept = d / link.url.rsplit("/", 1)[-1]
        if not kept.is_file():
            if not told:
                netlog.cause(FEATURE, f"You opened Free packs: a few sounds of "
                                      f"{netlog.quoted(pack.name)} to try, from Myinstants")
                told = True
            tmp = temp_folder("sb-linkpreview-")
            try:
                got = _fetch_link(link, tmp, pace, cancelled)
                shutil.move(str(got), kept)
            except Exception as e:  # noqa: BLE001 - gone, offline, switched off
                log.info("pack %s: no sample from %s (%s)", pack.id, link.url, e)
                errs.append(errors.plain(e))
                continue
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        found.append(Sample(link.name, b"", kept))
    if not found and errs:
        raise updates.UpdateError(errs[0])
    return found


def _samples(pack: Pack, cancelled: Callable[[], bool] | None) -> list[Sample]:
    d = previews_dir()
    zpath = d / f"{pack.id}.zip"
    if not zpath.is_file():   # the first time only: then it's served from here
        netlog.cause(FEATURE, f"You opened Free packs: a few sounds of "
                              f"{netlog.quoted(pack.name)} to try")
    updates.fetch(pack.preview_url, pack.preview_sha256, zpath, (updates.DOWNLOADS,),
                  PREVIEW_MAX, "pack", pack.preview_size, None, cancelled, feature=FEATURE)
    from soundboard.core import backup  # it imports the library's heavier parts
    try:
        pkg = backup.read(zpath)
    except backup.BackupError as e:
        raise updates.UpdateError(str(e)) from e
    out = d / pack.id
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)
    found = []
    with zipfile.ZipFile(zpath) as z:
        for i, ps in enumerate(pkg.sounds[:SAMPLES]):
            if sum(z.getinfo(n).file_size for n in (ps.audio, ps.picture) if n) > PREVIEW_MAX:
                continue   # far bigger unpacked than a short sound
            name = str(ps.entry.get("name") or "").strip()[:60]
            audio = out / f"{i}{Path(ps.audio).suffix.lower()}"
            audio.write_bytes(z.read(ps.audio))
            pic = z.read(ps.picture) if ps.picture else b""
            found.append(Sample(name or Path(ps.folder).name, pic, audio))
    return found
