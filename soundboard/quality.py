"""Settings > Data & quality: how much the app downloads and streams.

For slow, capped or mobile connections: smaller downloads, lower-bitrate radio
stations, more patience before a stream counts as dead, and no result pictures in
Sounds from the web. Also whether "Add as sound" keeps the video.

`current` is what the rest of the app reads (soundboard.ytdl, soundboard.radio,
ui.ytsearch); the Settings window changes it with change() and the config keeps it
as `Config.data` (a plain dict, like `radio` and `overlay`).
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from soundboard.i18n import _


class _Shown(Mapping):
    """A table whose labels are translated each time it's read: this module is imported
    before the language is set, so a plain dict would keep the English."""

    def __init__(self, make: Callable[[], dict]):
        self._make = make

    def __getitem__(self, key):
        return self._make()[key]

    def __iter__(self):
        return iter(self._make())

    def __len__(self):
        return len(self._make())


# "Add as sound" / Play: key -> (label, yt-dlp audio format)
DOWNLOADS = _Shown(lambda: {
    "best": (_("Best quality"), "bestaudio/best"),
    # YouTube's ~50-70 kbps Opus / 48 kbps AAC: about a third of "best", fine for a pad
    "small": (_("Smaller files"), "bestaudio[abr<=80]/worstaudio/bestaudio/best"),
})
# how sounds the app makes itself (a download, a recording) are saved: key -> label
# (library.stored_ext; files added from the PC are copied as they are)
SAVE_FORMATS = _Shown(lambda: {"mp3": _("MP3 (smaller)"), "flac": _("FLAC (lossless)")})
VIDEO_HEIGHTS = (1080, 720, 480, 360)
# Radio: the highest station bitrate shown (0 = any). Radio Browser lists most
# stations at 128 kbps; 64 and under are the "mobile" streams.
RADIO_KBPS = _Shown(lambda: {0: _("Any quality"), 128: _("Up to 128 kbps"),
                             64: _("Up to 64 kbps"), 32: _("Up to 32 kbps")})
LOW_RADIO_KBPS = 64
GLOBE_LOW = 1000              # stations the map fetches in low data mode (else radio's 3000)


def default_video_dir() -> Path:
    return Path.home() / "Videos" / "Onion Board"


@dataclass
class Prefs:
    download: str = "best"        # a DOWNLOADS key
    save_format: str = "mp3"      # a SAVE_FORMATS key
    save_video: bool = False      # "Add as sound" also keeps the video (needs ffmpeg)
    video_height: int = 720
    video_dir: str = ""           # "" = default_video_dir()
    radio_kbps: int = 0           # a RADIO_KBPS key
    patient: bool = False         # slow connection: wait longer, retry more (radio)
    web_extras: bool = True       # search result pictures

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
    if p.save_format not in SAVE_FORMATS:
        p.save_format = "mp3"
    if p.radio_kbps not in RADIO_KBPS:
        p.radio_kbps = 0
    if p.video_height not in VIDEO_HEIGHTS:
        p.video_height = 720
    return p


LOW = dict(download="small", save_video=False, radio_kbps=LOW_RADIO_KBPS, patient=True,
           web_extras=False)
NORMAL = dict(download="best", radio_kbps=0, patient=False, web_extras=True)

current = Prefs()
# keys of Config.data a newer version wrote, kept so a change here writes them back
_extra: dict = {}


def load(raw) -> Prefs:
    global current, _extra
    current = from_raw(raw)
    names = {f.name for f in fields(Prefs)}
    _extra = {k: v for k, v in raw.items() if k not in names} if isinstance(raw, dict) else {}
    return current


def change(**kw) -> dict:
    """Change some prefs; returns the dict to save as Config.data."""
    global current
    current = from_raw({**current.to_raw(), **kw})
    return {**_extra, **current.to_raw()}


def radio_fits(bitrate: int) -> bool:
    """A station at `bitrate` kbps is within the cap (unknown bitrates always are)."""
    cap = current.radio_kbps
    return not cap or not bitrate or bitrate <= cap
