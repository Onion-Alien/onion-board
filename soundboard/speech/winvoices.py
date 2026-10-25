"""Windows voices for other languages: install one in a click, notice new ones.

Settings -> Speech -> Add voices installs a Windows "capability" named
`Language.TextToSpeech~~~<locale>~0.0.1.0`. `install` does the same thing directly:
an elevated PowerShell (one UAC prompt) runs Add-WindowsCapability, which downloads
the voice from Windows Update. No Settings pages to find.

`fingerprint` is the set of voice tokens in the registry. It is cheap (no process),
so the panel polls it: when it changes, a voice came or went and the speech engine
is reloaded to pick it up, however it was installed.
"""
from __future__ import annotations

import base64
import shutil
import subprocess
import tempfile
from pathlib import Path

from soundboard.online import net
from soundboard.core import errors
from soundboard.win import systools

INSTALL_TIMEOUT_S = 30 * 60      # a slow Windows Update download
ERROR_CANCELLED = 1223           # the UAC prompt was answered No

# the locale Settings picks for a language when there are several
LOCALES = {
    "ar": "ar-SA", "bg": "bg-BG", "ca": "ca-ES", "cs": "cs-CZ", "da": "da-DK",
    "de": "de-DE", "el": "el-GR", "en": "en-US", "es": "es-ES", "fi": "fi-FI",
    "fr": "fr-FR", "he": "he-IL", "hi": "hi-IN", "hu": "hu-HU", "id": "id-ID",
    "it": "it-IT", "ja": "ja-JP", "ko": "ko-KR", "ms": "ms-MY", "nb": "nb-NO",
    "nl": "nl-NL", "pl": "pl-PL", "pt": "pt-BR", "ro": "ro-RO", "ru": "ru-RU",
    "sk": "sk-SK", "sl": "sl-SI", "sv": "sv-SE", "th": "th-TH", "tr": "tr-TR",
    "uk": "uk-UA", "vi": "vi-VN", "zh": "zh-CN"
}

_TOKEN_KEYS = (r"SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens",
               r"SOFTWARE\Microsoft\Speech\Voices\Tokens")

# runs elevated; answers in the $Out file: OK / RESTART / ALREADY <name>, or ERR <why>.
# Handed over whole on the command line (-EncodedCommand), never as a file: one in the
# user's %TEMP% could be swapped by anything running as them while the UAC prompt was
# open, and then run as admin.
_ELEVATED = r"""
$Locale = '__LOCALE__'
$Out = '__OUT__'
$ErrorActionPreference = 'Stop'
function Say($t) { [IO.File]::WriteAllText($Out, $t, [Text.Encoding]::UTF8) }
try {
    $lang = $Locale.Split('-')[0]
    $caps = @(Get-WindowsCapability -Online |
        Where-Object { $_.Name -like "Language.TextToSpeech~~~$lang-*" })
    if ($caps.Count -eq 0) { Say "ERR Windows offers no $Locale voice for this PC"; exit 2 }
    $cap = @($caps | Where-Object { $_.Name -like "*~~~$Locale~*" })[0]
    if (-not $cap) { $cap = $caps[0] }
    if ($cap.State -eq 'Installed') { Say "ALREADY $($cap.Name)"; exit 0 }
    $r = Add-WindowsCapability -Online -Name $cap.Name
    if ($r.RestartNeeded) { Say "RESTART $($cap.Name)" } else { Say "OK $($cap.Name)" }
    exit 0
} catch {
    Say ("ERR " + ($_.Exception.Message -replace "`r?`n", ' ').Trim())
    exit 1
}
"""

# runs as the user: starts the one above elevated and waits for it
_OUTER = r"""
try {
    $p = Start-Process '__POWERSHELL__' -Verb RunAs -WindowStyle Hidden -Wait -PassThru `
        -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass',
                        '-EncodedCommand', '__ELEVATED__')
    exit $p.ExitCode
} catch {
    [Console]::Out.WriteLine($_.Exception.Message)
    # ERROR_CANCELLED: the UAC prompt was answered No (the message text is localized)
    $e = $_.Exception
    if ($e.NativeErrorCode -eq 1223 -or $e.InnerException.NativeErrorCode -eq 1223) { exit 1223 }
    exit 1
}
"""


def _ps_quote(s) -> str:
    """`s` for inside a single-quoted PowerShell string: ' is written ''."""
    return str(s).replace("'", "''")


class Cancelled(Exception):
    """The user said No to the Windows permission prompt."""


LOCALE_RE = re.compile(r"[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*")


def _encoded(script: str) -> str:
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def locale_for(lang: str) -> str:
    if "-" in lang:
        return lang
    lang = lang.lower()
    return LOCALES.get(lang, f"{lang}-{lang.upper()}")


def fingerprint() -> frozenset[str]:
    """Every installed voice's registry token name (empty off Windows)."""
    try:
        import winreg
    except ImportError:
        return frozenset()
    names = set()
    for sub in _TOKEN_KEYS:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, sub) as k:
                i = 0
                while True:
                    try:
                        names.add(winreg.EnumKey(k, i))
                    except OSError:
                        break
                    i += 1
        except OSError:
            continue
    return frozenset(names)


def outcome(code: int, stdout: str, answer: str) -> str:
    """"ok" / "restart" / "already" from what the two scripts said; raises otherwise."""
    answer = answer.strip()
    if not answer:
        # the elevated script never ran; the outer one exits 1223 for a UAC "No"
        # (the English text check is a fallback for an older outer script)
        if code == ERROR_CANCELLED or (code and "cancel" in stdout.lower()):
            raise Cancelled()
        if code and stdout.strip():
            raise RuntimeError(stdout.strip())
    if answer.startswith("ERR"):
        raise RuntimeError(answer[3:].strip() or "the install failed")
    for word in ("OK", "RESTART", "ALREADY"):
        if answer.startswith(word):
            return word.lower()
    raise RuntimeError(f"the installer stopped without saying why (code {code})")


def install(lang: str, timeout: float = INSTALL_TIMEOUT_S) -> str:
    """Install Windows' voice for `lang`: "ok", "restart" (Windows wants a reboot to
    finish) or "already". Blocks for the download; raises Cancelled or RuntimeError
    (also when "Download voices and speech models" is off: Windows Update can't be
    sent through the app's connection, so it isn't started at all)."""
    if not net.allowed("voices"):
        raise RuntimeError(net.off_message("voices"))
    locale = locale_for(lang)
    if not LOCALE_RE.fullmatch(locale):
        raise RuntimeError(f"not a language name: {locale!r}")
    tmp = Path(tempfile.mkdtemp(prefix="sb-voice-"))
    try:
        out = tmp / "answer.txt"   # only what it says: swapped, it just says something else
        # the values land in single-quoted strings: a user folder like O'Brien is fine
        elevated = (_ELEVATED.replace("__LOCALE__", _ps_quote(locale))
                    .replace("__OUT__", _ps_quote(out)))
        outer = (_OUTER.replace("__POWERSHELL__", _ps_quote(systools.tool("powershell")))
                 .replace("__ELEVATED__", _encoded(elevated)))
        try:
            r = subprocess.run(
                [systools.tool("powershell"), "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-EncodedCommand", _encoded(outer)],
                capture_output=True, text=True, errors="replace", timeout=timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            raise RuntimeError("Windows took too long downloading the voice") from None
        except OSError as e:
            raise RuntimeError(f"couldn't start PowerShell: {errors.plain(e)}") from None
        answer = out.read_text(encoding="utf-8-sig") if out.exists() else ""
        return outcome(r.returncode, r.stdout or "", answer)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
