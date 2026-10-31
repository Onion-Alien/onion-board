"""Downloads for soundboard.online.ytdl: one link's audio (yt-dlp, in its helper
process, or a Myinstants file directly), looking a link up, yt-dlp's options and
its errors in plain words, and keeping the video."""
from __future__ import annotations

import contextlib
import html
import logging
import re
import shutil
import tempfile
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

from soundboard.online import jsengine, net, ytworker
from soundboard.sounds import library, sourceinfo
from soundboard.online import quality
from soundboard.sounds.library import MAX_SECONDS
from soundboard.core import errors
from soundboard.i18n import _
from soundboard.online.ytsites import (BROWSER_HEADERS, DownloadError, FEATURE, FetchError,
    IMAGE_EXTS, MAX_BYTES, MYINSTANTS, PROGRESS_EVERY_S, RETRY_CHECK_AFTER, RETRY_CLIENTS,
    RETRY_PAUSE_S, Result, SwitchedOff, TorBlocked, UPDATE_FEATURE, VIDEO_EXTS, VIDEO_MAX_BYTES,
    _TRY_AGAIN, _gate, _lock, _over_tor, _site_name)
from soundboard.online.ytupdate import (_pkg_dir, _purge, _save_state, _state, cache_dir, due,
    install, override_version, root, update)

log = logging.getLogger("soundboard.online.ytdl")


# ---------------------------------------------------------------------- downloading

def downloadable(url: str) -> bool:
    """Worth offering "Add as sound" for: a video / track page, not a site's home
    page or a search. yt-dlp decides for real; this only greys the button out."""
    m = re.match(r"https?://(?:[\w-]+\.)*([\w-]+\.[a-z]+)(/[^?#]*)?(\?[^#]*)?", url, re.I)
    if not m:
        return False
    host, path, query = m.group(1).lower(), m.group(2) or "", m.group(3) or ""
    if host in ("youtube.com", "youtu.be"):
        return bool(re.search(r"[?&]v=[\w-]{6,}", query)) or \
            bool(re.match(r"/(shorts|live|embed)/[\w-]{6,}", path)) or \
            (host == "youtu.be" and len(path) > 6)
    return path.strip("/") != "" and not path.startswith(("/search", "/results"))


def as_link(text: str) -> str:
    """`text` as a web link if it is one ("www.…" gets https://), else "". Only
    http(s): a typed file:// or data: link is never handed to yt-dlp."""
    t = text.strip()
    if re.match(r"www\.[\w-]+\.", t, re.I):
        t = "https://" + t
    return t if re.fullmatch(r"https?://[\w.-]+\.[a-z]{2,}(:\d+)?([/?#]\S*)?", t, re.I) else ""


MAX_LINKS = 30    # links pasted at once that are looked up (the download queue's size)


def as_links(text: str) -> list[str]:
    """Two or more web links pasted together (on lines of their own, or with spaces or
    commas between), each once, at most MAX_LINKS; [] when it's one link, or any word
    in it isn't one (then it's a search)."""
    words = [w for w in text.replace(",", " ").split() if w]
    if len(words) < 2 or len(words) > 10 * MAX_LINKS:
        return []
    links = [as_link(w) for w in words]
    if not all(links):
        return []
    unique = list(dict.fromkeys(links))
    return unique[:MAX_LINKS] if len(unique) > 1 else []


TITLE_MAX = 300   # a title's characters looked at (a pad name keeps far fewer)


def clean_title(title: str) -> str:
    """A pad name from a video title: no "(Official Video)" / "[HD]" noise, no HTML
    entities (TikTok's come as "&amp;"), no " - Sound Button" (a Myinstants page's)."""
    # cut first, and bounded brackets: a site's title is any length, and an open bracket
    # with no end before a long run of words took minutes, holding the whole app
    title = html.unescape(title[:TITLE_MAX * 2])[:TITLE_MAX]
    t = re.sub(r"\s*[(\[][^)\]]{0,80}?\b(official|video|audio|lyrics?|hd|4k|visuali[sz]er)\b"
               r"[^)\]]{0,80}[)\]]", "", title, flags=re.I)
    t = re.sub(r"\s+[-|]\s+sound button\s*$", "", t, flags=re.I)
    return re.sub(r"\s+", " ", t).strip() or title.strip()


def download_audio(url: str, dest: Path | None = None,
                   progress: Callable[[float], None] | None = None,
                   auto_update: bool = True, direct: bool = False,
                   video: bool = False, thumbnail: bool = True) -> tuple[Path, str]:
    """Download the audio of `url` into `dest` (a new temp folder by default), at
    Settings > Data & quality's download quality; with `video`, the video with its
    sound in one file (save_video() keeps a copy, the pad is still decoded from it).

    Returns (file, title). `progress` gets 0..1 while it downloads. If yt-dlp fails
    and no update check ran in the last hour, it updates yt-dlp and tries once more.
    Raises DownloadError with a message fit to show the user (SwitchedOff when its
    site is switched off in Settings > Privacy & security, TorBlocked when the site
    turned Tor away). `direct` skips the Connection setting (not the switches) for
    this one download: only for the user's own "Try this one without Tor" click.
    `thumbnail` False skips the video's picture (Play once has no pad to show it on):
    yt-dlp tries the biggest sizes first and YouTube takes seconds to say each of
    those doesn't exist, ~12 s before the audio even starts."""
    feature = _gate(url)
    if url.startswith(MYINSTANTS + "/media/sounds/"):
        if direct:
            return _download_direct(url, dest, progress, direct=True)
        return _over_tor(lambda: _download_direct(url, dest, progress), url)

    extra: dict[str, bool] = {"video": True} if video else {}
    if not thumbnail:
        extra["thumbnail"] = False

    def fetch(again: bool = False):
        more = dict(extra, again=True) if again else extra
        if direct:
            return _download(url, dest, progress, feature, direct=True, **more)
        return _over_tor(lambda: _download(url, dest, progress, feature, **more), url)
    try:
        return fetch()
    except FetchError as first:
        e = first
    if _worth_another_try(e):
        # most of these pass by themselves: try once more, YouTube with other players,
        # before the user sees an error (and gives up on the app)
        log.info("%s failed (%s); trying once more", _site_name(url), e)
        time.sleep(RETRY_PAUSE_S)
        try:
            done = fetch(again=True)
        except FetchError as second:
            e = second
        else:
            _count_used("dl-retried-ok")
            return done
    if (isinstance(e, TorBlocked) or not auto_update or not due(RETRY_CHECK_AFTER)
            or not net.allowed(UPDATE_FEATURE)):
        raise e
    before = override_version()
    try:
        msg = update()
    except Exception as ue:  # noqa: BLE001
        log.info("yt-dlp update after a failed download didn't work: %s", ue)
        raise e from None
    if override_version() != before:   # a newer copy came in (not "up to date")
        log.info("%s Retrying %s", msg, url)
        return fetch()
    raise e


def _worth_another_try(e: FetchError) -> bool:
    """A failure a second try often gets past (_TRY_AGAIN): not one over Tor (_over_tor
    has its own tries, with new identities) or the proxy's fault."""
    if isinstance(e, TorBlocked) or getattr(e, "proxy", False) or net.mode() == net.TOR:
        return False
    return bool(_TRY_AGAIN.search(f"{getattr(e, 'raw', '')} {e}"))


def _count_used(name: str) -> None:
    """usage.used(), imported here only (usage imports from this package)."""
    try:
        from soundboard.core import usage
        usage.used(name)
    except Exception:  # noqa: BLE001 - counting never breaks a download
        log.debug("couldn't count %s", name, exc_info=True)


def probe(url: str, direct: bool = False) -> tuple[str, float]:
    """Look `url` up without downloading anything: (clean title, seconds or 0).
    Raises DownloadError like download_audio (but never updates yt-dlp)."""
    r = lookup(url, direct)
    return r.title, r.seconds


def lookup(url: str, direct: bool = False) -> Result:
    """A pasted link as a search hit: its title, channel, length, picture and counts,
    nothing downloaded (the search box shows it as a card to play or add). Raises
    DownloadError like probe."""
    feature = _gate(url)
    if url.startswith(MYINSTANTS + "/media/sounds/"):
        return Result(_direct_leaf(url), _direct_title(url), "Myinstants", 0.0,
                      source="link", link=url)

    def look():
        return _check(_extract(url, _opts(feature=feature, direct=direct)))
    return _as_result(url, look() if direct else _over_tor(look, url))


class Playlist(list):
    """A pasted playlist's first videos (Results), with its name and how many it has
    in all (0 when the site didn't say)."""
    def __init__(self, title: str, hits, total: int = 0):
        super().__init__(hits)
        self.title, self.total = title, total


def lookup_all(url: str, direct: bool = False) -> Result | Playlist:
    """lookup(), but a playlist (YouTube, a SoundCloud set…) is no error: its first
    MAX_LINKS videos (the cards show them to add one by one or all at once). YouTube's
    come from its list in one request; other sites' are looked up one by one."""
    feature = _gate(url)
    if url.startswith(MYINSTANTS + "/media/sounds/"):
        return lookup(url, direct)
    opts: dict[str, object] = dict(_opts(feature=feature, direct=direct), playlistend=MAX_LINKS,
                                   ignoreerrors=True)   # a private or deleted one: left out
    if feature == f"{FEATURE}.youtube":   # YouTube lists each video's name and length;
        opts["extract_flat"] = "in_playlist"   # other sites (SoundCloud) only the link

    def look():
        return _extract(url, opts)
    info = look() if direct else _over_tor(look, url)
    if not info:   # ignoreerrors hid why: lookup() raises it, in plain words
        return lookup(url, direct)
    if info.get("_type") != "playlist":
        return _as_result(url, _check(info))
    from soundboard.online.ytsearch import _soundcloud_hit, _youtube_hit
    hits: list[Result] = []
    for e in info.get("entries") or ():
        if (not e or e.get("live_status") == "is_live"
                or re.fullmatch(r"\[(Private|Deleted) video\]", str(e.get("title")))):
            continue   # YouTube's list names them, but they can't be downloaded
        ie = str(e.get("ie_key") or e.get("extractor_key") or "")
        if ie.startswith("Youtube"):
            hit = _youtube_hit(e)
        elif ie.startswith("Soundcloud"):
            hit = _soundcloud_hit(e)
        else:   # another site's list: its link, and the title if it gave one
            link = str(e.get("webpage_url") or e.get("url") or "")
            hit = (Result(str(e.get("id") or link), clean_title(str(e.get("title") or ""))
                          or _("Sound"), str(e.get("uploader") or ""),
                          float(e.get("duration") or 0), source="link", link=link)
                   if link.startswith(("https://", "http://")) else None)
        if hit and all(h.url != hit.url for h in hits):
            hits.append(hit)
    if not hits:
        raise DownloadError(_("That playlist is empty, or its videos are private."))
    total = info.get("playlist_count")
    return Playlist(clean_title(str(info.get("title") or "")),
                    hits[:MAX_LINKS], total if isinstance(total, int) else 0)


def _as_result(url: str, info: dict) -> Result:
    """A looked-up video's info as a search hit (lookup)."""
    def count(key):
        v = info.get(key)
        return int(v) if isinstance(v, (int, float)) else None
    return Result(str(info.get("id") or url), clean_title(info.get("title") or "") or _("Sound"),
                  str(info.get("uploader") or info.get("channel") or info.get("creator") or ""),
                  float(info.get("duration") or 0), source="link", link=url,
                  art=str(info.get("thumbnail") or ""), views=count("view_count"),
                  likes=count("like_count"), comments=count("comment_count"))


def _drop_broken(error: BaseException):
    """The downloaded copy doesn't import (it needs a newer Python, or a package this
    app doesn't have): delete it and never fetch that version again. The built-in
    copy is what imports next."""
    with _lock.exclusive():
        version = override_version()
        if not version:
            return   # dropped already (another thread, or the download helper)
        log.warning("downloaded yt-dlp %s doesn't import (%s): using the built-in one",
                    version, error)
        _save_state(bad=sorted(set(_state().get("bad") or ()) | {version}), version="")
        gone = root() / f"bad-{time.time_ns()}"
        try:
            _pkg_dir().rename(gone)
        except OSError:
            log.warning("couldn't move the broken yt-dlp aside", exc_info=True)
        shutil.rmtree(gone, ignore_errors=True)
        _purge()


@contextlib.contextmanager
def _ydl():
    """The yt_dlp module, in shared use (an update never swaps it mid-use). A
    downloaded copy that fails to import is dropped for the built-in one."""
    install()
    for retry in (False, True):
        with _lock.shared():
            try:
                import yt_dlp
            except Exception as e:  # noqa: BLE001 - a broken copy can raise anything
                failed = e
            else:
                yield yt_dlp
                return
        if retry or not override_version():
            raise FetchError(_("The downloader (yt-dlp) isn't installed, "
                               "Settings → Updates → Helper programs → yt-dlp → "
                               "Reinstall.")) from failed
        _drop_broken(failed)


def _download(url, dest, progress, feature: str = FEATURE,
              direct: bool = False, video: bool = False,
              thumbnail: bool = True, again: bool = False) -> tuple[Path, str]:
    with _ydl() as yt_dlp:
        if dest:
            return _run(yt_dlp, url, Path(dest), progress, feature, direct, video, thumbnail,
                        again)
        # Our own temp folder: the caller only learns it on success, so a failed
        # download (up to the size cap) must not be left behind in %TEMP%.
        tmp = Path(tempfile.mkdtemp(prefix="sb-ytdl-"))
        try:
            return _run(yt_dlp, url, tmp, progress, feature, direct, video, thumbnail, again)
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise


def _direct_leaf(url: str) -> str:
    """The file name of a direct link, safe to put in our folder: only the last path
    segment (never the query), decoded, with separators / `..` / odd characters gone."""
    leaf = urllib.parse.unquote(urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1])
    return re.sub(r"[^\w .()-]", "_", leaf).strip(" .")[:80]


def _direct_title(url: str) -> str:
    stem = _direct_leaf(url).rsplit(".", 1)[0]
    return re.sub(r"[-_]+", " ", stem).strip().capitalize() or _("Sound")


def _download_direct(url, dest, progress, direct: bool = False) -> tuple[Path, str]:
    """A plain audio file yt-dlp can't fetch (Myinstants' Cloudflare blocks it)."""
    parts = urllib.parse.urlsplit(url)
    leaf = _direct_leaf(url)
    # the URL comes from a paste: a query / fragment / odd name could steer the file
    # out of our folder (Windows resolves `\..` inside the name)
    if (parts.netloc != urllib.parse.urlsplit(MYINSTANTS).netloc or parts.query
            or parts.fragment or not leaf.lower().endswith(".mp3")):
        raise DownloadError(_("That isn't a Myinstants sound link."))
    tmp = Path(dest) if dest else Path(tempfile.mkdtemp(prefix="sb-ytdl-"))
    path = tmp / leaf
    if path.resolve().parent != tmp.resolve():
        if not dest:
            shutil.rmtree(tmp, ignore_errors=True)
        raise DownloadError(_("That isn't a Myinstants sound link."))
    def drop():   # nothing half-downloaded is left behind
        if dest:
            path.unlink(missing_ok=True)
        else:
            shutil.rmtree(tmp, ignore_errors=True)

    try:
        req = urllib.request.Request(url, headers=BROWSER_HEADERS)
        with (net.urlopen(req, timeout=30, feature=f"{FEATURE}.myinstants",
                          direct=direct) as r,
              open(path, "wb") as f):
            total, got = int(r.headers.get("Content-Length") or 0), 0
            while chunk := r.read(64 * 1024):
                got += len(chunk)
                if got > MAX_BYTES:
                    raise _too_big(MAX_BYTES)
                f.write(chunk)
                if progress and total:
                    progress(min(got / total, 1.0))
            if total and got != total:   # a dropped connection just ends read()
                raise DownloadError(_("Download failed ({error})",
                                      error=_("The connection was dropped.")))
        with open(path, "rb") as f:   # a page or anything else under an .mp3 name isn't kept
            head = f.read(4)
        frame = len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0
        if not (head[:3] == b"ID3" or frame):
            raise DownloadError(_("That isn't a Myinstants sound link."))
    except DownloadError:
        drop()
        raise
    except net.FeatureOff as e:
        drop()
        raise SwitchedOff(str(e)) from None
    except Exception as e:  # noqa: BLE001 - network: show why
        drop()
        raise DownloadError(_("Download failed ({error})", error=errors.plain(e))) from e
    title = _direct_title(url)
    sourceinfo.save_for(tmp, {"title": title}, url)   # the pad menu's Open on Myinstants
    return path, title


def _sendable(opts: dict) -> dict:
    """yt-dlp's options for the helper process: its own hooks and logger go there."""
    return {k: v for k, v in opts.items() if k not in ("progress_hooks", "logger")}


def _remote(e: ytworker.RemoteError) -> Exception:
    """yt-dlp's error from the helper as one of its own class name, for _readable."""
    module, _dot, name = e.kind.rpartition(".")
    return type(name or "Error", (Exception,), {"__module__": module or "yt_dlp"})(str(e))


def _extract(target: str, opts: dict, keep: bool = False) -> dict:
    """yt-dlp's look-up of `target` (nothing downloaded), in the helper process when
    the app has one (ytworker: it never holds up the sound), else here. `keep`: a
    YouTube search may reuse YouTube's settings from the last one (ytworker.extract)."""
    if ytworker.enabled:
        try:
            return ytworker.run("lookup", target, _sendable(opts), *([True] if keep else []))
        except ytworker.RemoteError as e:
            raise _readable(_remote(e)) from None
        except TimeoutError as e:
            out = FetchError(_("The site took too long to answer. Try again."))
            out.kind = "helper-timeout"
            raise out from e
        except ytworker.Unavailable as e:
            log.info("%s; looking it up here", e)
    with _ydl() as yt_dlp:
        try:
            return ytworker.extract(yt_dlp, target, opts, keep)
        except DownloadError:
            raise
        except Exception as e:  # noqa: BLE001 - yt-dlp raises many kinds; show its message
            raise _readable(e) from e


def _check(info: dict) -> dict:
    """Refuse what isn't one sound."""
    if info.get("_type") == "playlist":
        raise DownloadError(_("That's a playlist: open one video and try again."))
    if info.get("is_live"):
        raise DownloadError(_("Can't add a live stream, use Record instead."))
    return info


def _went_nowhere(url: str, msg: str) -> bool:
    """yt-dlp's "Unsupported URL" for a page `url` only redirected to: a share link
    (tiktok.com/t/…, vm.tiktok.com/…) of a deleted or private video lands on the site's
    home page. The site is fine; the video is gone."""
    m = re.search(r"Unsupported URL: (\S+)", msg)
    if not m:
        return False
    to = urllib.parse.urlsplit(m.group(1))
    return m.group(1).rstrip("/") != url.rstrip("/") and to.path.strip("/") == ""


def _readable(e: Exception) -> FetchError:
    """yt-dlp's error in plain words (errors.describe): no "[youtube] id:" prefix,
    command-line tips or "report this on yt-dlp's GitHub"; one we can't explain is
    marked for reporting to us. The original text stays in `.raw`."""
    p = errors.describe(e, downloader=True)
    text = p.text
    # through a proxy / Tor, "check your internet" was wrong when it's the proxy that
    # didn't answer: say what net.py saw ("Couldn't reach the proxy at ..."). yt-dlp
    # goes through the app's relay, which answers 502 when the proxy didn't, so "the
    # site is having trouble" was just as wrong
    if net.mode() != net.DIRECT and text in (
            _("Couldn't reach the site. Check your internet connection."),
            _("The site is having trouble right now. Try again later."),
            _("The connection timed out. Check your internet and try again.")):
        failure = net.last_failure(time.monotonic() - 60)
        # (an address that isn't usable already says where it is)
        if failure and net.mode() == net.PROXY and net.proxy() is not None:
            failure += " " + _("You can change the proxy in Settings > Connection.")
        text = failure or text
    out = FetchError(text)
    # the words shown are the problem's (errors.describe reads .problem back)
    out.problem = p if text == p.text else errors.Problem(text, p.detail)
    out.raw = str(e)
    # yt-dlp's class (_remote names it the same); its DownloadError keeps the one it wraps
    inner = getattr(e, "exc_info", None)
    cause = inner[1] if isinstance(inner, tuple) and len(inner) > 1 else None
    out.kind = type(cause if isinstance(cause, BaseException) else e).__name__
    out.proxy = text != p.text   # the proxy / Tor's fault: no newer yt-dlp fixes that
    return out


def _opts(dest: Path | None = None, progress=None, thumbnail: bool = False,
          feature: str = FEATURE, direct: bool = False, video: bool = False,
          again: bool = False) -> dict:
    last = [-1.0]
    stalled = ytworker.stall_guard(cap=VIDEO_MAX_BYTES if video else MAX_BYTES)

    def hook(d):
        if d.get("status") == "downloading":
            stalled(d.get("downloaded_bytes") or 0)
        if progress and d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            if total:
                # yt-dlp calls this for every block (hundreds a second on a fast
                # line), each a signal to the UI thread: PROGRESS_EVERY_S is plenty
                f = min(d.get("downloaded_bytes", 0) / total, 1.0)
                now = time.monotonic()
                if f < 1.0 and now - last[0] < PROGRESS_EVERY_S:
                    return
                last[0] = now
                progress(f)

    opts = {
        "format": quality.current.audio_format(),   # Settings > Data & quality
        "outtmpl": str((dest or Path(tempfile.gettempdir())) / "%(id)s.%(ext)s"),
        "noplaylist": True,            # a video in a playlist: just that video
        "writethumbnail": thumbnail,   # the pad's picture (soundboard.sounds.thumbs)
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "max_filesize": MAX_BYTES,
        "cachedir": str(cache_dir()),  # ours, so Reinstall can clear it
        "js_runtimes": jsengine.runtimes(),   # YouTube's player challenge; works without
        "progress_hooks": [hook],
        "logger": log,
    }
    # the relay, as this site: Settings > Connection and Privacy & security;
    # `direct` is the user's "Try this one without Tor" (the switches still hold)
    opts["proxy"] = net.ytdlp_proxy(feature, direct=direct)
    if again:   # download_audio's second try: YouTube's other players
        opts["extractor_args"] = {"youtube": {"player_client": list(RETRY_CLIENTS)}}
    if video:
        ff = library._ffmpeg()
        fmt = quality.current.video_format()
        if ff:   # yt-dlp merges the best video and audio streams with it
            opts.update(ffmpeg_location=ff, merge_output_format="mp4")
        else:    # no merging: only files that already hold both
            fmt = fmt.split("/", 2)[2]
        # no video to be had (SoundCloud has none; YouTube has no single files with
        # both any more, so without ffmpeg none of it fits): the sound alone, as Add
        # without the video would get it. Else yt-dlp says "Requested format is not
        # available" and the whole Add failed.
        fmt += "/" + quality.current.audio_format()
        opts.update(format=fmt, max_filesize=VIDEO_MAX_BYTES)
    return opts


def save_video(path: Path, title: str) -> Path | None:
    """Keep a downloaded video in Settings > Data & quality's videos folder, under its
    title. None when `path` isn't a video (a download that fell back to audio)."""
    path = Path(path)
    if path.suffix.lower() not in VIDEO_EXTS:
        return None
    folder = quality.current.videos()
    folder.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title).strip(" .")[:80] or "Video"
    out = folder / f"{stem}{path.suffix.lower()}"
    n = 2
    while out.exists():
        out = folder / f"{stem} ({n}){path.suffix.lower()}"
        n += 1
    shutil.copy2(path, out)
    return out


def _run(yt_dlp, url: str, dest: Path, progress, feature: str = FEATURE,
         direct: bool = False, video: bool = False, thumbnail: bool = True,
         again: bool = False) -> tuple[Path, str]:
    try:
        opts = _opts(dest, progress, thumbnail=thumbnail, feature=feature, direct=direct,
                     video=video, again=again)
        # a playlist's entries left unresolved: one private or deleted video in it
        # must not hide that it's a playlist (_check says so). A video isn't affected.
        opts["extract_flat"] = "in_playlist"
        done = _run_helper(url, opts, progress) if ytworker.enabled else None
        if done is not None:
            info, path = done
            return _found(url, dest, path, info)
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = _check(ydl.extract_info(url, download=False))
            dur = info.get("duration") or 0
            if dur > MAX_SECONDS:
                log.info("%s is %ds; only the first %ds will be kept", url, dur, MAX_SECONDS)
            ytworker.guard_requests(ydl)
            info = ydl.process_ie_result(info, download=True)
            path = Path(ydl.prepare_filename(info))
    except DownloadError:
        raise
    except ytworker.Stalled as e:
        raise FetchError(_("The download stopped moving. Try again.")) from e
    except ytworker.TooBig as e:
        raise _too_big(VIDEO_MAX_BYTES if video else MAX_BYTES) from e
    except Exception as e:  # noqa: BLE001 - yt-dlp raises many kinds; show its message
        if _went_nowhere(url, str(e)):
            raise FetchError(_("That video isn't available any more.")) from e
        raise _readable(e) from e
    return _found(url, dest, path, info)


def _too_big(cap: int) -> DownloadError:
    e = DownloadError(_("It's over {mb} MB.", mb=cap // 2**20))
    e.dl_why = "too-big"   # errors.download_reason: the words are translated
    return e


DOWNLOAD_QUIET_S = 300   # a helper download that says nothing for this long is stuck


def _run_helper(url: str, opts: dict, progress) -> tuple[dict, Path] | None:
    """_run's yt-dlp part in the helper process (ytworker); None: do it here."""
    try:
        info, name = ytworker.run("download", url, _sendable(opts), MAX_SECONDS,
                                  timeout=DOWNLOAD_QUIET_S, progress=progress)
    except ytworker.RemoteError as e:
        if e.kind.endswith(".Stalled"):
            raise FetchError(_("The download stopped moving. Try again.")) from None
        if e.kind.endswith(".TooBig"):
            raise _too_big(opts.get("max_filesize") or MAX_BYTES) from None
        if _went_nowhere(url, str(e)):
            raise FetchError(_("That video isn't available any more.")) from None
        raise _readable(_remote(e)) from None
    except TimeoutError as e:
        raise FetchError(_("The download stopped moving. Try again.")) from e
    except ytworker.Unavailable as e:
        log.info("%s; downloading here", e)
        return None
    info = _check(info)
    if (info.get("duration") or 0) > MAX_SECONDS:
        log.info("%s is %ds; only the first %ds will be kept", url, info["duration"],
                 MAX_SECONDS)
    return info, Path(name)


def _found(url: str, dest: Path, path: Path, info: dict) -> tuple[Path, str]:
    """The file a download made, and its title."""
    if not path.is_file():   # skipped (too big) or the extension changed
        found = [p for p in dest.iterdir() if p.is_file() and not p.name.endswith(".part")
                 and p.suffix.lower() not in IMAGE_EXTS]
        if not found:
            e = DownloadError(_("Nothing was downloaded (the file may be over {mb} MB).",
                                mb=MAX_BYTES // 2**20))
            e.dl_why = "too-big"   # yt-dlp skips a file over max_filesize
            raise e
        path = found[0]
    sourceinfo.save_for(path.parent, info, url)   # the pad menu's Open on YouTube
    return path, clean_title(info.get("title") or path.stem)
