"""Other libraries' errors in plain words, reported to us (soundboard.core.errors)."""
from urllib.parse import unquote

import pytest
from yt_dlp.utils import DownloadError, bug_reports_message

from soundboard.core import errors


def test_yt_dlp_known_errors_are_plain_and_not_for_reporting():
    e = DownloadError(
        "ERROR: [youtube] dQw4w9WgXcQ: Private video. Sign in if you've been granted "
        "access to this video. Use --cookies-from-browser or --cookies for the "
        "authentication. See  https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-"
        "cookies-to-yt-dlp  for how to manually pass cookies")
    p = errors.describe(e)
    assert p.text == "That video is private."
    assert not p.reportable


def test_youtube_this_video_is_unavailable_is_plain():
    """YouTube's wording for a deleted video: it was shown as "The downloader ran into
    a problem" with a Report it link."""
    p = errors.describe(DownloadError("ERROR: [youtube] aaaaaaaaaaa: This video is unavailable"))
    assert p.text == "That video isn't available any more."
    assert not p.reportable


def test_yt_dlp_report_upstream_text_becomes_a_report_to_us():
    e = DownloadError("ERROR: [youtube] dQw4w9WgXcQ: Unable to extract initial player "
                      "response" + bug_reports_message())
    p = errors.describe(e)
    assert p.reportable
    for gone in ("yt-dlp/issues", "yt-dlp -U", "report this", "[youtube]", "ERROR"):
        assert gone not in p.text
    assert "Unable to extract initial player response" in p.text
    url = unquote(errors.report_url(p, "Adding a link"))
    assert "github.com/Onion-Alien/onion-board/issues/new" in url
    assert "Adding a link" in url and "Unable to extract" in url


def test_a_site_refusing_a_download_isnt_counted_as_the_app_going_wrong(monkeypatch):
    """yt-dlp's words we have no plain version of still get a Report it link, but
    aren't sent as a warned/ count: the site said no, the count can't say why, and
    the download's own failure count already has it."""
    from soundboard.core import usage
    from soundboard.online import ytdl
    counted = []
    monkeypatch.setattr(usage, "warned", counted.append)
    try:
        raise ytdl._readable(DownloadError("ERROR: [youtube] x: Some new refusal"))
    except ytdl.FetchError as e:
        shown = errors.html(e)
    assert "Report it" in shown
    assert counted == []
    try:
        raise KeyError("ours")
    except KeyError as e:
        errors.html(e)
    assert len(counted) == 1     # the app's own bugs still count


@pytest.mark.parametrize("text", [
    "x; please report this issue on  https://github.com/foo/bar/issues , thanks",
    "Use --cookies-from-browser or --cookies for the authentication.",
    "See  https://github.com/yt-dlp/yt-dlp/wiki/FAQ  for how to do it",
])
def test_clean_drops_other_projects_advice(text):
    out = errors.clean(text)
    assert "github.com" not in out and "--cookies" not in out


def test_os_errors_in_plain_words():
    assert errors.plain(PermissionError(13, "Permission denied")).startswith("Windows denied")
    assert errors.plain(FileNotFoundError(2, "nope")) == "The file isn't there any more."
    e = OSError(28, "No space left on device")
    assert errors.plain(e) == "The disk is full."
    # our own OSError("sentence") keeps its sentence
    assert errors.plain(OSError("couldn't save it. Try again.")) == "couldn't save it. Try again."


def test_bugs_are_reportable_but_dont_show_python_jargon():
    p = errors.describe(KeyError("volume"))
    assert p.reportable and "KeyError" not in p.text and "KeyError" in p.detail


def test_our_own_messages_are_kept():
    from soundboard.online.ytdl import DownloadError as OurError
    p = errors.describe(OurError("That's a playlist — open one video and try again."))
    assert p.text == "That's a playlist — open one video and try again."
    assert not p.reportable


def test_unreadable_sound_file(tmp_path):
    import soundfile
    bad = tmp_path / "x.mp3"
    bad.write_bytes(b"not audio at all" * 10)
    with pytest.raises(Exception) as info:
        soundfile.read(str(bad))
    assert errors.plain(info.value) == "It isn't a sound file that can be read, or it's damaged."


def test_a_device_that_wont_open_isnt_called_a_bad_sound_file():
    """PortAudio's message starts like libsndfile's ("Error opening ..."): a mic or
    headphones that won't open (Windows' audio restarting, say) is a device problem."""
    import sounddevice
    e = sounddevice.PortAudioError(
        "Error opening OutputStream: Invalid sample rate [PaErrorCode -9997]")
    assert errors.plain(e) == "That audio device doesn't support the sample rate needed."
    e = sounddevice.PortAudioError("Error opening InputStream: Unanticipated host error "
                                   "[PaErrorCode -9999]")
    assert "sound file" not in errors.plain(e)


def test_report_link_only_when_reportable():
    assert errors.report_link(errors.Problem("Private.")) == ""
    assert "Report it" in errors.report_link(errors.Problem("Odd.", "d", True))
    assert "Report it" not in errors.html("That video is private.")


def test_details_are_scrubbed(monkeypatch):
    from pathlib import Path
    home = str(Path.home())
    p = errors.describe(KeyError(f"{home}\\secret.txt"))
    assert home not in p.detail


def test_the_original_error_is_kept_for_reports_and_the_log(caplog):
    import logging
    e = DownloadError("ERROR: [youtube] dQw4w9WgXcQ: Private video. Use --cookies for it.")
    with caplog.at_level(logging.INFO, logger="soundboard.core.errors"):
        p = errors.describe(e)
    assert p.text == "That video is private."
    assert "Private video. Use --cookies for it." in p.detail   # what a report carries
    assert "Private video. Use --cookies for it." in caplog.text   # and the log
    assert "Use --cookies" in unquote(errors.report_url(p))


@pytest.mark.parametrize("raw, why", [
    ("ERROR: [youtube] abc: Sign in to confirm you’re not a bot. Use --cookies", "bot"),
    ("ERROR: [youtube] abc: Sign in to confirm your age", "age"),
    ("ERROR: unable to download video data: HTTP Error 403: Forbidden", "403"),
    ("ERROR: [youtube] abc: Video unavailable. This video is private", "private"),
    ("ERROR: [youtube] abc: Video unavailable", "gone"),
    ("The read operation timed out", "timeout"),
    ("no new data for 60 s", "stalled"),
    ("Something nobody has seen", "other"),
])
def test_a_failed_download_has_one_short_reason_for_the_count(raw, why):
    from soundboard.core import usage
    e = RuntimeError("shown words")
    e.raw = raw
    assert errors.download_reason(e) == why
    assert why in usage.DL_FAILS


@pytest.mark.parametrize("raw, why", [
    ("ERROR: [youtube] abc: Requested format is not available", "no-formats"),
    ("The site wants to check you're not a robot.", "bot"),   # the app's own words
    ("The site refused the download (403).", "403"),
    ("Couldn't reach the site. Check your internet connection.", "offline"),
])
def test_download_reasons_read_both_ytdlps_and_our_words(raw, why):
    assert errors.download_reason(raw) == why


def test_a_full_disk_is_said_plainly_and_never_counted_as_a_new_problem():
    """yt-dlp's "[Errno 28]" and our own OSError (writing the cache) both say the disk
    is full, and count as disk-full, not as a download failure to look into."""
    from soundboard.core import usage
    raw = "ERROR: unable to write data: [Errno 28] No space left on device"
    e = RuntimeError(raw)
    assert errors.download_reason(e) == "disk-full"
    assert "disk is full" in errors.describe(DownloadError(raw)).text
    assert errors.download_reason(OSError(28, "Kein Speicherplatz")) == "disk-full"
    assert "disk-full" in usage.DL_FAILS


def test_our_own_download_errors_keep_their_reason_in_any_language(monkeypatch):
    """Their words are translated, the reason patterns are English: a missing FFmpeg
    or a file over the size cap must not count as an unknown failure for a German user."""
    from soundboard.core import usage
    from soundboard.online import ytfetch
    from soundboard.sounds import decoding
    monkeypatch.setattr(decoding, "_ffmpeg", lambda: None)
    with pytest.raises(RuntimeError) as got:
        with decoding._ffmpeg_source("x.webm"):
            pass
    assert errors.download_reason(got.value) == "no-ffmpeg"
    big = ytfetch._too_big(ytfetch.MAX_BYTES)
    big.args = ("Es ist über 300 MB groß.",)
    assert errors.download_reason(big) == "too-big"
    assert {"no-ffmpeg", "too-big"} <= set(usage.DL_FAILS)


def test_a_report_link_never_carries_the_home_folder_in_what_it_said(monkeypatch, tmp_path):
    """The message itself can name a path (a downloader error): it goes in the address
    the browser opens, so it's scrubbed like the details are."""
    from soundboard.core import applog
    monkeypatch.setattr(applog.Path, "home", lambda: tmp_path / "Ann")
    p = errors.Problem(f"Couldn't write {tmp_path / 'Ann' / 'Music' / 'x.mp3'}",
                       reportable=True)
    url = unquote(errors.report_url(p))
    assert str(tmp_path / "Ann") not in url and "%USERPROFILE%" in url
