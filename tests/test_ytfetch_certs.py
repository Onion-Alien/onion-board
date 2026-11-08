"""yt-dlp's connection failures in plain words, and its certificate check falling back
to Windows' list (soundboard.online.ytfetch). The texts are yt-dlp 2026.08.19's own,
for a YouTube search through a local proxy that broke each connection in its way."""
import pytest

from soundboard.core import errors, usage
from soundboard.online import ytfetch, ytworker
from soundboard.online.ytsites import FetchError

_TAIL = ("; please report this issue on  https://github.com/yt-dlp/yt-dlp/issues?q= , "
         "filling out the appropriate issue template. Confirm you are on the latest "
         "version using  yt-dlp -U")
CERT = ('ERROR: query "rain sounds" page 1: Unable to download API page: [SSL: '
        "CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate "
        "(_ssl.c:1028) (caused by CertificateVerifyError('[SSL: CERTIFICATE_VERIFY_FAILED] "
        "certificate verify failed: self-signed certificate (_ssl.c:1028)'))" + _TAIL)
WRONG_VERSION = ('ERROR: query "rain sounds" page 1: Unable to download API page: [SSL: '
                 "WRONG_VERSION_NUMBER] wrong version number (_ssl.c:1028) (caused by "
                 "SSLError('[SSL: WRONG_VERSION_NUMBER] wrong version number "
                 "(_ssl.c:1028)'))" + _TAIL)
CLOSED = ('ERROR: query "rain sounds" page 1: Unable to download API page: Remote end '
          "closed connection without response (caused by TransportError('Remote end "
          "closed connection without response'))")
ABORTED = ('ERROR: query "rain sounds" page 1: Unable to download API page: [WinError '
           "10053] An established connection was aborted by the software in your host "
           "machine (caused by TransportError('[WinError 10053] An established connection "
           "was aborted by the software in your host machine'))")
TLS_WORDS = ("Something blocked the secure connection to the site, often antivirus web "
             "protection, a school or work network, or a Wi-Fi sign-in page.")
OFFLINE_WORDS = "Couldn't reach the site. Check your internet connection."


def _ytdlp_error(text: str, cause: str = "") -> Exception:
    """yt-dlp's DownloadError as the download helper hands it back (ytfetch._remote)."""
    return ytfetch._remote(ytworker.RemoteError("yt_dlp.utils.DownloadError", text, cause))


@pytest.mark.parametrize("text, why, words", [
    (CERT, "tls", TLS_WORDS),
    (WRONG_VERSION, "tls", TLS_WORDS),
    (CLOSED, "offline", OFFLINE_WORDS),
    (ABORTED, "offline", OFFLINE_WORDS),
])
def test_a_broken_connection_is_said_plainly_with_its_own_reason(text, why, words):
    """These were "another reason" (the TLS ones) or yt-dlp's raw text with a Report
    button: something on the way broke the connection, which the user can do something
    about and isn't ours to fix."""
    e = ytfetch._readable(_ytdlp_error(text))
    assert str(e) == words
    assert errors.download_reason(e) == why
    assert why in usage.DL_FAILS
    assert not errors.describe(e).reportable


def test_a_handshake_that_only_timed_out_is_still_a_timeout():
    e = ytfetch._readable(_ytdlp_error(
        "ERROR: Unable to download API page: _ssl.c:989: The handshake operation timed out"))
    assert errors.download_reason(e) == "timeout"


def test_the_helper_sends_the_error_yt_dlp_wrapped_so_the_count_can_tell_them_apart():
    """A DownloadError from the helper counted as "DownloadError" whatever it was: the
    error it wraps (a refused certificate, YouTube's page changing) goes with it, as for
    an error in the app's own process."""
    class CertificateVerifyError(Exception):
        pass
    inner = CertificateVerifyError("certificate verify failed")
    from yt_dlp.utils import DownloadError
    sent = ytworker._error(DownloadError(CERT, (type(inner), inner, None)))
    assert sent == ("yt_dlp.utils.DownloadError", CERT, "CertificateVerifyError")
    got = ytfetch._readable(ytfetch._remote(ytworker.RemoteError(*sent)))
    assert got.kind == "CertificateVerifyError"
    assert usage.error_detail(got)[0].startswith("CertificateVerifyError")
    # an error without one is counted by its own class, as before
    assert ytworker._error(ValueError("x")) == ("builtins.ValueError", "x", "")
    assert ytfetch._readable(_ytdlp_error("Some new refusal")).kind == "DownloadError"


@pytest.fixture
def certifi_first(monkeypatch):
    monkeypatch.setattr(ytfetch, "_windows_certs", False)


def test_a_refused_certificate_tries_windows_certificates_and_keeps_them(monkeypatch,
                                                                         certifi_first):
    """Antivirus web protection and school / work networks add their certificate to
    Windows' list only: yt-dlp's own list (certifi) refused every search there."""
    calls = []

    def once(target, opts, keep=False):
        calls.append(dict(opts))
        if "compat_opts" not in opts:
            raise ytfetch._readable(_ytdlp_error(CERT))
        return {"entries": []}
    monkeypatch.setattr(ytfetch, "_extract_once", once)
    assert ytfetch._extract("ytsearch5:rain", {"quiet": True}) == {"entries": []}
    assert [c.get("compat_opts") for c in calls] == [None, ["no-certifi"]]
    # from now on, straight away: every search and download uses Windows' list
    assert ytfetch._opts()["compat_opts"] == ["no-certifi"]


def test_windows_certificates_are_tried_once_and_other_failures_not_at_all(monkeypatch,
                                                                         certifi_first):
    calls = []

    def once(target, opts, keep=False):
        calls.append(opts.get("compat_opts"))
        raise ytfetch._readable(_ytdlp_error(CERT if len(calls) < 3 else CLOSED))
    monkeypatch.setattr(ytfetch, "_extract_once", once)
    with pytest.raises(FetchError) as got:   # Windows' list refuses it too: said plainly
        ytfetch._extract("ytsearch5:rain", {})
    assert str(got.value) == TLS_WORDS
    assert calls == [None, ["no-certifi"]]
    with pytest.raises(FetchError):          # already on Windows' list: no second go
        ytfetch._extract("ytsearch5:rain", {})
    assert len(calls) == 3


def test_a_download_whose_certificate_is_refused_tries_windows_certificates(monkeypatch,
                                                                         certifi_first):
    seen = []

    def once(*args):
        seen.append(ytfetch._opts().get("compat_opts"))
        if not ytfetch._windows_certs:
            raise ytfetch._readable(_ytdlp_error(CERT))
        return "file", "title"
    monkeypatch.setattr(ytfetch, "_run_once", once)
    assert ytfetch._run(None, "https://youtu.be/x", None, None) == ("file", "title")
    assert seen == [None, ["no-certifi"]]


def test_other_failures_are_not_retried_with_windows_certificates(monkeypatch,
                                                                  certifi_first):
    calls = []

    def once(*args):
        calls.append(1)
        raise ytfetch._readable(_ytdlp_error(WRONG_VERSION))
    monkeypatch.setattr(ytfetch, "_run_once", once)
    with pytest.raises(FetchError):
        ytfetch._run(None, "https://youtu.be/x", None, None)
    assert calls == [1]
    assert not ytfetch._windows_certs
