"""Settings > Data & quality: how much the app downloads and streams.

For slow, capped or mobile connections: smaller downloads, lower-bitrate radio
stations, more patience before a stream counts as dead, and no result pictures or
like counts in Sounds from the web. Also whether "Add as sound" keeps the video.

`current` is what the rest of the app reads (soundboard.ytdl, soundboard.radio,
ui.ytsearch); the Settings window changes it with change() and the config keeps it
as `Config.data` (a plain dict, like `radio` and `overlay`).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from pathlib import Path

# "Add as sound" / Play: key -> (label, yt-dlp audio format)
DOWNLOADS = {
    "best": ("Best quality", "bestaudio/best"),
    # YouTube's ~50-70 kbps Opus / 48 kbps AAC: about a third of "best", fine for a pad
    "small": ("Smaller files", "bestaudio[abr<=80]/worstaudio/bestaudio/best"),
}
VIDEO_HEIGHTS = (1080, 720, 480, 360)
# Radio: the highest station bitrate shown (0 = any). Radio Browser lists most
# stations at 128 kbps; 64 and under are the "mobile" streams.
RADIO_KBPS = {0: "Any quality", 128: "Up to 128 kbps", 64: "Up to 64 kbps",
              32: "Up to 32 kbps"}
LOW_RADIO_KBPS = 64
GLOBE_LOW = 1000              # stations the map fetches in low data mode (else radio's 3000)


def default_video_dir() -> Path:
    return Path.home() / "Videos" / "Onion Board"


@dataclass
class Prefs:
    download: str = "best"        # a DOWNLOADS key
    save_video: bool = False      # "Add as sound" also keeps the video (needs ffmpeg)
    video_height: int = 720
    video_dir: str = ""           # "" = default_video_dir()
    radio_kbps: int = 0           # a RADIO_KBPS key
    patient: bool = False         # slow connection: wait longer, retry more (radio)
    web_extras: bool = True       # search result pictures + like / comment counts

    def audio_format(self) -> str:
        return DOWNLOADS.get(self.download, DOWNLOADS["best"])[1]

    def video_format(self) -> str:
        """Video + audio in one file. Merging separate streams needs ffmpeg (yt-dlp's
        merger); the plain fallbacks are single files with both (360p on YouTube)."""
        h = self.video_height
        return (f"bv*[height<={h}][ext=mp4]+ba[ext=m4a]/bv*[height<={h}]+ba/"
                f"b[height<={h}][vcodec!=none][acodec!=none]/b[vcodec!=none][acodec!=none]")

    def videos(self) -> Path:
        return Path(self.video_dir) if self.video_dir else default_video_dir()

    @property
    def low_data(self) -> bool:
        """Every choice at its lightest (the "Low data mode" switch shows this)."""
        return (self.download == "small" and not self.save_video and self.patient
                and 0 < self.radio_kbps <= LOW_RADIO_KBPS and not self.web_extras)

    def to_raw(self) -> dict:
        return asdict(self)


def from_raw(raw) -> Prefs:
    """Prefs from a saved dict; anything missing or odd keeps its default."""
    p = Prefs()
    if not isinstance(raw, dict):
        return p
    for f in fields(Prefs):
        v = raw.get(f.name)
        if type(v) is type(getattr(p, f.name)):   # exact: a bool isn't an int here
            setattr(p, f.name, v)
    if p.download not in DOWNLOADS:
        p.download = "best"
    if p.radio_kbps not in RADIO_KBPS:
        p.radio_kbps = 0
    if p.video_height not in VIDEO_HEIGHTS:
        p.video_height = 720
    return p


LOW = dict(download="small", save_video=False, radio_kbps=LOW_RADIO_KBPS, patient=True,
           web_extras=False)
NORMAL = dict(download="best", radio_kbps=0, patient=False, web_extras=True)

current = Prefs()


def load(raw) -> Prefs:
    global current
    current = from_raw(raw)
    return current


def change(**kw) -> dict:
    """Change some prefs; returns the dict to save as Config.data."""
    global current
    current = from_raw({**current.to_raw(), **kw})
    return current.to_raw()


def radio_fits(bitrate: int) -> bool:
    """A station at `bitrate` kbps is within the cap (unknown bitrates always are)."""
    cap = current.radio_kbps
    return not cap or not bitrate or bitrate <= cap
