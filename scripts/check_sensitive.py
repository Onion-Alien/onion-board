"""Scan the repo for secrets and personal information before it goes public.

    python scripts/check_sensitive.py             # files that would be published
    python scripts/check_sensitive.py --staged    # what is about to be committed
    python scripts/check_sensitive.py --history   # every blob + commit message ever

Built-in rules catch credential formats and machine-identifying data (user
profile paths, LAN / Tailscale IPs, default Windows host names, e-mail
addresses). Your own identifiers (real name, handles, host names) go in
`.sensitive-patterns` -- one regex per line, gitignored so the list of things
you want hidden is not itself published. See `scripts/sensitive-patterns.example`.

A line containing `sensitive-scan: allow` is skipped. Exit status 1 = findings.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRIVATE_PATTERNS = ROOT / ".sensitive-patterns"
MAX_BYTES = 2_000_000
ALLOW_MARK = "sensitive-scan: allow"

RULES: list[tuple[str, re.Pattern[str]]] = [(name, re.compile(rx)) for name, rx in (
    # --- credentials
    ("private key", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ("AWS access key", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    ("GitHub token", r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})\b"),
    ("Slack token", r"\bxox[abposr]-[A-Za-z0-9-]{10,}"),
    ("Anthropic key", r"\bsk-ant-[A-Za-z0-9_-]{20,}"),
    ("OpenAI key", r"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}"),
    ("Google API key", r"\bAIza[0-9A-Za-z_-]{35}\b"),
    ("Discord webhook", r"discord(?:app)?\.com/api/webhooks/\d+/[\w-]+"),
    ("Discord bot token", r"\b[MNO][A-Za-z\d_-]{23,25}\.[A-Za-z\d_-]{6}\.[A-Za-z\d_-]{27,}\b"),
    ("URL with password", r"\b[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s:@]+@"),
    ("hardcoded secret", r"(?i)\b(?:api[_-]?key|secret|passw(?:or)?d|auth[_-]?token"
                         r"|access[_-]?token)\s*[:=]\s*['\"][^'\"\s]{12,}['\"]"),
    # --- machine / person identifying
    ("Windows user path", r"(?i)\b[A-Z]:[\\/]{1,2}Users[\\/]{1,2}"
                          r"(?!Public\b|Default\b|runneradmin\b|<|\{|%|\$|\*)[^\\/\s\"'<>]+"),
    ("Unix home path", r"(?<![\w.])/(?:home|Users)/(?!runner\b|<|\{|\$|\*)[A-Za-z0-9._-]+"),
    ("Windows default hostname", r"\bDESKTOP-[A-Z0-9]{7}\b"),
    ("Tailscale / CGNAT IP", r"\b100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b"),
    ("private LAN IP", r"\b(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b"),
    ("e-mail address", r"\b[A-Za-z0-9._%+-]+@(?!example\.(?:com|org)\b)"
                       r"(?!users\.noreply\.github\.com\b)[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
)]

# e-mails that are fine to publish
EMAIL_OK = re.compile(r"(?i)^(?:noreply|no-reply)@|@anthropic\.com$"
                      r"|^support@github\.com$")  # dependabot's Signed-off-by


def load_private_rules() -> list[tuple[str, re.Pattern[str]]]:
    if not PRIVATE_PATTERNS.exists():
        return []
    out = []
    for n, line in enumerate(PRIVATE_PATTERNS.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if line and not line.startswith("#"):
            try:
                out.append((f"private pattern #{n}", re.compile(line, re.IGNORECASE)))
            except re.error as e:
                sys.exit(f"{PRIVATE_PATTERNS.name}:{n}: bad regex: {e}")
    return out


def git(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=True).stdout


def redact(s: str) -> str:
    return s if len(s) <= 8 else s[:4] + "..." + s[-2:]


def scan_text(label: str, text: str, rules) -> list[str]:
    hits = []
    for ln, line in enumerate(text.splitlines(), 1):
        if ALLOW_MARK in line:
            continue
        for name, rx in rules:
            for m in rx.finditer(line):
                if name == "e-mail address" and EMAIL_OK.search(m.group(0)):
                    continue
                hits.append(f"{label}:{ln}: {name}: {redact(m.group(0))}")
    return hits


def decode(data: bytes) -> str | None:
    if len(data) > MAX_BYTES or b"\0" in data[:8192]:
        return None  # binary or huge: check those by hand (see the release checklist)
    return data.decode("utf-8", errors="replace")


SELF = {"scripts/check_sensitive.py", "scripts/sensitive-patterns.example", ".sensitive-patterns",
        ".sensitive-patterns.example"}   # (the example's old path, for --history)


def scan_worktree(rules, staged: bool) -> list[str]:
    if staged:
        names = git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z").split(b"\0")
    else:  # tracked + untracked-but-not-ignored = what `git add -A` would publish
        names = git("ls-files", "-co", "--exclude-standard", "-z").split(b"\0")
    hits = []
    for raw in filter(None, names):
        name = raw.decode()
        if name in SELF or (not staged and not (ROOT / name).is_file()):
            continue  # deleted in the working tree (still in the index) = nothing to publish
        data = git("show", f":{name}") if staged else (ROOT / name).read_bytes()
        text = decode(data)
        if text is not None:
            hits += scan_text(name, text, rules)
    return hits


def git_in(stdin: bytes, *args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=ROOT, input=stdin, capture_output=True,
                          check=True).stdout


def history_blobs():
    """(path, sha, bytes) for every file version ever committed, read by one
    `git cat-file --batch` instead of two git processes per object (minutes -> s)."""
    paths = {}
    for line in git("rev-list", "--all", "--objects").decode().splitlines():
        sha, _, path = line.partition(" ")
        if path and path not in SELF:
            paths.setdefault(sha, path)
    check = git_in("\n".join(paths).encode(), "cat-file",
                   "--batch-check=%(objectname) %(objecttype) %(objectsize)")
    blobs = []
    for line in check.decode().splitlines():
        sha, kind, size = line.split()
        if kind == "blob" and int(size) <= MAX_BYTES:   # bigger: decode() skips them
            blobs.append(sha)
    out, pos = git_in("\n".join(blobs).encode(), "cat-file", "--batch"), 0
    for sha in blobs:
        end = out.index(b"\n", pos)
        size = int(out[pos:end].split()[2])
        yield paths[sha], sha, out[end + 1:end + 1 + size]
        pos = end + 1 + size + 1                         # the data's own newline


def scan_history(rules) -> list[str]:
    hits = []
    for path, sha, data in history_blobs():
        text = decode(data)
        if text is not None:
            hits += scan_text(f"{path}@{sha[:8]}", text, rules)
    log = git("log", "--all", "--format=%H%x00%an <%ae>%x00%cn <%ce>%x00%B%x01").decode()
    authors = set()
    for entry in filter(str.strip, log.split("\x01")):
        sha, author, committer, body = entry.strip().split("\0", 3)
        authors |= {author, committer}
        hits += scan_text(f"commit {sha[:8]} message", body, rules)
    tags = git("for-each-ref", "refs/tags",
               "--format=%(refname:short)%00%(taggername) %(taggeremail)%00%(contents)%01").decode()
    for entry in filter(str.strip, tags.split("\x01")):
        name, tagger, body = entry.strip().split("\0", 2)
        if tagger.strip():  # annotated tag
            authors.add(tagger)
        hits += scan_text(f"tag {name} message", body, rules)
    print("Identities in commit metadata (these become public with the history):")
    for a in sorted(authors):
        print(f"  {a}")
    print()
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--staged", action="store_true", help="scan the index (pre-commit)")
    g.add_argument("--history", action="store_true", help="scan every blob and commit message")
    args = ap.parse_args()

    private = load_private_rules()
    if not private:
        print(f"note: no {PRIVATE_PATTERNS.name} file -- only built-in rules are active\n")
    rules = RULES + private
    hits = scan_history(rules) if args.history else scan_worktree(rules, args.staged)
    for h in hits:
        print(h)
    print(f"\n{len(hits)} finding(s)." if hits else "No findings.")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
