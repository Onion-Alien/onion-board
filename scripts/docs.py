"""Rebuild the README's and the website's pictures and release line in one go.

    .venv\\Scripts\\python scripts\\docs.py                    # screenshots + version line
    .venv\\Scripts\\python scripts\\docs.py --vt <sha256> 68/68 # after a release's VirusTotal scan
    .venv\\Scripts\\python scripts\\docs.py --tour             # also re-record tour.webp
    .venv\\Scripts\\python scripts\\docs.py --no-shots         # only the text

The version comes from soundboard/__init__.py; the VirusTotal scan is remembered in
docs/release.json, so it only needs passing once per release. The line is rewritten
between the <!-- release --> markers in README.md and docs/index.html, and the
sitemap's dates are set to today. Every screenshot link gets ?v=<hash of the picture>,
so nobody is shown an old cached copy after the pictures change.

Screenshots are screenshots.py (offscreen, made-up data, the Retro 98 theme). Set
ONIONBOARD_ONION_WATCH_ZIP to an OnionWatch-module.zip to include the Triggers tab.
--tour runs tour.py, which drives a real window parked off-screen for about a minute.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RELEASE = ROOT / "docs" / "release.json"
SHOTS = ROOT / "docs" / "screenshots"
REPO = "https://github.com/Onion-Alien/onion-board"


def version() -> str:
    text = (ROOT / "soundboard" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__ = "([^"]+)"', text).group(1)


def vt_link(r: dict) -> str:
    return f"https://www.virustotal.com/gui/file/{r['vt_sha256']}"


def readme_block(r: dict) -> str:
    vt = f"VirusTotal: {r['vt_clean']} of {r['vt_total']} clean"
    return (f"Version **{r['version']}** · Windows 10 / 11 · free, no account, no ads, "
            f"anonymous usage count you can switch off ·\n"
            f"[{vt}]({vt_link(r)}) ·\n[what's new](CHANGELOG.md)")


def site_block(r: dict) -> str:
    vt = f"VirusTotal: {r['vt_clean']} of {r['vt_total']} clean"
    return (f'    <p class="small">Version {r["version"]} · Windows 10 / 11 · free, no account, '
            f'no ads, anonymous usage count you can switch off<br>\n'
            f'      <a href="{vt_link(r)}">{vt}</a> ·\n'
            f'      <a href="{REPO}/releases/latest">what\'s new</a></p>')


def stamp(path: Path, block: str):
    text = path.read_text(encoding="utf-8")
    new, n = re.subn(r"(<!-- release -->\n).*?(\n\s*<!-- /release -->)",
                     lambda m: m.group(1) + block + m.group(2), text, flags=re.S)
    if n != 1:
        raise SystemExit(f"{path.name}: expected one <!-- release --> block, found {n}")
    path.write_text(new, encoding="utf-8")
    print("stamped", path.relative_to(ROOT))


PAGES = [ROOT / "README.md", ROOT / "docs" / "index.html",
         *sorted((ROOT / "docs").glob("*/index.html"))]   # the guide pages


def bust_caches():
    """Give each screenshot link a ?v=<hash of the picture>, so browsers and GitHub's
    image proxy fetch a changed picture instead of showing the old one they kept."""
    def tag(m):
        pic = SHOTS / m.group(2)
        if not pic.exists():
            return m.group(0)
        h = hashlib.sha1(pic.read_bytes()).hexdigest()[:8]
        return f"{m.group(1)}{m.group(2)}?v={h}"
    for page in PAGES:
        text = page.read_text(encoding="utf-8")
        new = re.sub(r"(screenshots/)([\w-]+\.(?:png|webp))(?:\?v=\w+)?", tag, text)
        if new != text:
            page.write_text(new, encoding="utf-8")
            print("re-linked pictures in", page.relative_to(ROOT))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vt", nargs=2, metavar=("SHA256", "CLEAN/TOTAL"),
                    help="the release installer's VirusTotal scan, e.g. --vt 4267e4cf... 68/68")
    ap.add_argument("--no-shots", action="store_true", help="skip the screenshots")
    ap.add_argument("--tour", action="store_true", help="also re-record docs/screenshots/tour.webp")
    args = ap.parse_args()

    r = json.loads(RELEASE.read_text(encoding="utf-8"))
    if r["version"] != version() and not args.vt:
        print(f"note: VirusTotal scan is for {r['version']}; pass --vt for {version()}'s installer")
    r["version"] = version()
    if args.vt:
        clean, total = args.vt[1].split("/")
        r.update(vt_sha256=args.vt[0].lower(), vt_clean=int(clean), vt_total=int(total))
    RELEASE.write_text(json.dumps(r, indent=2) + "\n", encoding="utf-8")

    stamp(ROOT / "README.md", readme_block(r))
    stamp(ROOT / "docs" / "index.html", site_block(r))
    sitemap = ROOT / "docs" / "sitemap.xml"
    # UTC, like the commit times and the CHANGELOG: a local date can give away the timezone
    today = datetime.datetime.now(datetime.UTC).date().isoformat()
    sitemap.write_text(re.sub(r"<lastmod>[^<]*</lastmod>", f"<lastmod>{today}</lastmod>",
                              sitemap.read_text(encoding="utf-8")), encoding="utf-8")

    if not args.no_shots:
        if not os.environ.get("ONIONBOARD_ONION_WATCH_ZIP"):
            print("note: ONIONBOARD_ONION_WATCH_ZIP isn't set, so triggers.png stays as it is")
        start = time.time()
        # judged by the pictures it wrote: it sometimes crashes on its way out (os._exit
        # with Qt's threads still running), after everything is saved
        subprocess.run([sys.executable, "-u", str(ROOT / "scripts" / "screenshots.py"),
                        "--out", str(SHOTS)], cwd=ROOT)
        stale = [p.name for p in SHOTS.glob("*.png") if p.stat().st_mtime < start
                 and (p.name != "triggers.png" or os.environ.get("ONIONBOARD_ONION_WATCH_ZIP"))]
        if stale:
            raise SystemExit(f"screenshots.py didn't redo: {', '.join(stale)}")
    if args.tour:
        subprocess.run([sys.executable, str(ROOT / "scripts" / "tour.py"),
                        "--out", str(SHOTS / "tour.webp")], cwd=ROOT, check=True)
    bust_caches()


if __name__ == "__main__":
    main()
