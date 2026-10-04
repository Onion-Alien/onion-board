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
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from soundboard import net
from soundboard import errors

INSTALL_TIMEOUT_S = 30 * 60      # a slow Windows Update download
ERROR_CANCELLED = 1223           # the UAC prompt was answered No

# the locale Settings picks for a language when there are several
LOCALES = {
    "ar": "ar-SA", "cs": "cs-CZ", "da": "da-DK", "de": "de-DE", "el": "el-GR",
    "en": "en-US", "es": "es-ES", "fi": "fi-FI", "fr": "fr-FR", "he": "he-IL",
    "hi": "hi-IN", "hu": "hu-HU", "id": "id-ID", "it": "it-IT", "ja": "ja-JP",
    "ko": "ko-KR", "nb": "nb-NO", "nl": "nl-NL", "pl": "pl-PL", "pt": "pt-BR",
    "ro": "ro-RO", "ru": "ru-RU", "sk": "sk-SK", "sv": "sv-SE", "th": "th-TH",
    "tr": "tr-TR", "uk": "uk-UA", "vi": "vi-VN", "zh": "zh-CN",
}

_TOKEN_KEYS = (r"SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens",
               r"SOFTWARE\Microsoft\Speech\Voices\Tokens")

# runs elevated; answers in the -Out file: OK / RESTART / ALREADY <name>, or ERR <why>
_ELEVATED = r"""
param([string]$Locale, [string]$Out)
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
    $p = Start-Process powershell.exe -Verb RunAs -WindowStyle Hidden -Wait -PassThru `
        -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', '"__SCRIPT__"',
                        '-Locale', '__LOCALE__', '-Out', '"__OUT__"')
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


def has_language(tokens: frozenset[str], lang: str) -> bool:
    """Whether a token looks like a `lang` voice: MSTTS_V110_zhCN_HuihuiM, TTS_MS_ZH-CN_…"""
    pat = re.compile(rf"_{re.escape(lang.upper())}[A-Z]{{2}}_")
    return any(pat.search(t.upper().replace("-", "")) for t in tokens)


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
    tmp = Path(tempfile.mkdtemp(prefix="sb-voice-"))
    try:
        script, out = tmp / "install-voice.ps1", tmp / "answer.txt"
        script.write_text(_ELEVATED, encoding="utf-8")
        # the values land in single-quoted strings: a user folder like O'Brien is fine
        outer = (_OUTER.replace("__LOCALE__", _ps_quote(locale_for(lang)))
                 .replace("__OUT__", _ps_quote(out)).replace("__SCRIPT__", _ps_quote(script)))
        enc = base64.b64encode(outer.encode("utf-16-le")).decode("ascii")
        try:
            r = subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-EncodedCommand", enc],
                capture_output=True, text=True, timeout=timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            raise RuntimeError("Windows took too long downloading the voice") from None
        except OSError as e:
            raise RuntimeError(f"couldn't start PowerShell: {errors.plain(e)}") from None
        answer = out.read_text(encoding="utf-8-sig") if out.exists() else ""
        return outcome(r.returncode, r.stdout or "", answer)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
