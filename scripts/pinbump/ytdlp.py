"""Add the newest yt-dlp release to pins/yt-dlp.json, the list of yt-dlp versions the
app's "Update now" (soundboard/ytdl.py) may install. Unlike the other pins this one
isn't built into the app: the app reads the list from the repo's main branch, so a
merged PR here is what approves a version. Before proposing one it checks:

- the yt-dlp wheel and the yt-dlp-ejs wheel it pins (`yt-dlp-ejs==X`) match PyPI's
  SHA-256, and each carries a PyPI attestation (PEP 740) signed by its own GitHub
  repo's release workflow (yt-dlp/yt-dlp, yt-dlp/ejs), checked with pypi-attestations
  (sigstore): a release uploaded with a stolen PyPI token has none;
- the two together import and run `yt-dlp --version` on a Windows runner.

The app itself only installs a listed version once it has been on PyPI for 3 days.
With --dry-run it also checks every listed wheel's SHA-256 and address against PyPI
(a hand-edited list gets checked too). See common.py.

    python scripts/pinbump/ytdlp.py [--dry-run]

Needs `pip install -r scripts/pinbump/requirements.txt` (pypi-attestations).
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

LIST = common.ROOT / "pins" / "yt-dlp.json"
KEEP = 6            # versions kept in the list: older ones to fall back on
WHEEL_HOST = "https://files.pythonhosted.org/"
WHEEL_MAX = 30_000_000
REPOS = {"yt-dlp": "yt-dlp/yt-dlp", "yt-dlp-ejs": "yt-dlp/ejs"}   # who must have signed
ABOUT = ("yt-dlp versions Onion Board's Update now may install (soundboard/ytdl.py). "
         "Added by scripts/pinbump/ytdlp.py, which checks each wheel against PyPI's "
         "SHA-256 and its attestation from the yt-dlp GitHub repos; a merged PR approves "
         "a version. The app waits until a version has been on PyPI for 3 days.")


def pypi(name: str, version: str = "") -> dict:
    return common.fetch_json(f"https://pypi.org/pypi/{name}/{version + '/' if version else ''}json")


def wheel_of(meta: dict) -> dict:
    """The release's pure-Python wheel (what the app unpacks)."""
    for f in meta.get("urls", ()):
        if f["filename"].endswith("-py3-none-any.whl") and not f.get("yanked"):
            return f
    sys.exit(f"no py3-none-any wheel in {meta['info']['name']} {meta['info']['version']}")


def ejs_pin(meta: dict) -> str:
    for r in meta["info"].get("requires_dist") or ():
        if m := re.match(r"yt-dlp-ejs\s*==\s*([\w.]+)", r):
            return m.group(1)
    sys.exit(f"yt-dlp {meta['info']['version']} pins no yt-dlp-ejs version")


def attested(name: str, version: str, f: dict, path: Path) -> None:
    """Exits unless PyPI has an attestation for this file signed by REPOS[name]."""
    prov = common.fetch_json(
        f"https://pypi.org/integrity/{name}/{version}/{f['filename']}/provenance",
        {"Accept": "application/vnd.pypi.integrity.v1+json"})
    pf = path.with_suffix(".provenance.json")
    pf.write_text(json.dumps(prov), encoding="utf-8")
    common.run([sys.executable, "-m", "pypi_attestations", "verify", "pypi",
                "--repository", f"https://github.com/{REPOS[name]}",
                "--provenance-file", pf, path], expect="OK:")


def checked_wheel(name: str, version: str, d: Path) -> tuple[dict, Path]:
    """Download and verify one wheel; its entry for the list and where it was saved."""
    meta = meta_for(name, version)
    f = wheel_of(meta)
    if not f["url"].startswith(WHEEL_HOST):
        sys.exit(f"{f['filename']} is at {f['url']}, not on {WHEEL_HOST}")
    data = common.fetch(f["url"], WHEEL_MAX)
    digest = common.sha256(data)
    if digest != f["digests"]["sha256"]:
        sys.exit(f"{f['filename']} hashes to {digest}, PyPI says {f['digests']['sha256']}")
    path = d / f["filename"]
    path.write_bytes(data)
    attested(name, version, f, path)
    print(f"{name} {version}: sha256 {digest} matches PyPI, attestation from "
          f"{REPOS[name]} verified, {len(data)} bytes")
    return {"name": name, "version": version, "filename": f["filename"], "url": f["url"],
            "sha256": digest, "size": len(data),
            "requires_python": f.get("requires_python") or ""}, path


_metas: dict[tuple[str, str], dict] = {}


def meta_for(name: str, version: str) -> dict:
    if (name, version) not in _metas:
        _metas[name, version] = pypi(name, version)
    return _metas[name, version]


def smoke(wheels: list[Path], version: str) -> None:
    """The two wheels unpacked together run `yt-dlp --version`, as the app's copy would."""
    with tempfile.TemporaryDirectory() as d:
        for w in wheels:
            with zipfile.ZipFile(w) as z:
                z.extractall(d)
        out = common.run([sys.executable, "-I", "-c",
                          f"import runpy, sys; sys.path.insert(0, {d!r}); import yt_dlp_ejs; "
                          "sys.argv = ['yt-dlp', '--version']; "
                          "runpy.run_module('yt_dlp', run_name='__main__')"])
        said = out.strip().splitlines()[-1] if out.strip() else ""
        # it prints 2026.08.19 for PyPI's 2026.8.19
        if not re.fullmatch(r"\d+(\.\d+)+", said) or (
                common.version_key(said) != common.version_key(version)):
            sys.exit(f"smoke FAILED: yt-dlp --version said {said!r}, not {version}")


def entry(version: str) -> dict:
    meta = meta_for("yt-dlp", version)
    pin = ejs_pin(meta)
    with tempfile.TemporaryDirectory() as d:
        main, main_path = checked_wheel("yt-dlp", version, Path(d))
        ejs, ejs_path = checked_wheel("yt-dlp-ejs", pin, Path(d))
        smoke([main_path, ejs_path], version)
    return {"version": version, "uploaded": wheel_of(meta)["upload_time_iso_8601"],
            "wheels": [main, ejs]}


def check_listed(listing: dict) -> None:
    """Every listed wheel is the one PyPI has under that name and version."""
    for e in listing["versions"]:
        for w in e["wheels"]:
            f = wheel_of(meta_for(w["name"], w["version"]))
            if (f["filename"], f["url"], f["digests"]["sha256"]) != (
                    w["filename"], w["url"], w["sha256"]):
                sys.exit(f"listed {w['filename']} doesn't match PyPI's {f['filename']} "
                         f"({f['url']}, sha256 {f['digests']['sha256']})")
    print(f"ytdlp: the {len(listing['versions'])} listed versions match PyPI")


def main() -> int:
    a = common.args()
    listing = json.loads(LIST.read_text(encoding="utf-8"))
    have = [e["version"] for e in listing["versions"]]
    new = str(pypi("yt-dlp")["info"]["version"])
    if not re.fullmatch(r"\d+(\.\d+)+", new):
        sys.exit(f"PyPI's latest yt-dlp is {new!r}, not a release version")
    print(f"ytdlp: listed {', '.join(have) or 'none'}; newest on PyPI {new}")
    if a.dry_run:
        check_listed(listing)
    if new in have:
        if not a.dry_run:
            return 0
        print("ytdlp: up to date; verifying the newest anyway (--dry-run)")
    elif common.already_open("ytdlp", new):
        print(f"ytdlp: {common.branch_for('ytdlp', new)} already exists, skipping")
        return 0
    e = entry(new)
    if a.dry_run:
        print(json.dumps(e, indent=2))
        return 0
    versions = [e] + [x for x in listing["versions"] if x["version"] != new]
    versions.sort(key=lambda x: common.version_key(x["version"]), reverse=True)
    LIST.write_text(json.dumps({"about": ABOUT, "versions": versions[:KEEP]}, indent=2)
                    + "\n", encoding="utf-8", newline="\n")
    main_w, ejs_w = e["wheels"]
    common.open_pr(
        "ytdlp", new, [LIST], f"yt-dlp: approve {new} for Update now",
        f"Weekly pin bump: adds yt-dlp {new} (with yt-dlp-ejs {ejs_w['version']}) to "
        "`pins/yt-dlp.json`. Merging this approves it: the app's *Update now* (and the "
        "opt-in automatic update) may then install it, once it has been on PyPI for 3 "
        f"days (uploaded {e['uploaded']}).\n\n"
        f"- `{main_w['filename']}`: SHA-256 `{main_w['sha256']}`, matches PyPI; PyPI "
        "attestation signed by yt-dlp/yt-dlp's release workflow, verified.\n"
        f"- `{ejs_w['filename']}`: SHA-256 `{ejs_w['sha256']}`, matches PyPI; "
        "attestation signed by yt-dlp/ejs, verified.\n"
        "- Smoke test: the two unpacked together ran `yt-dlp --version` on a Windows "
        "runner.\n"
        f"- Changelog: https://github.com/yt-dlp/yt-dlp/releases/tag/{new}\n\n"
        "Before merging, skim the release notes and its GitHub page for reports of a bad "
        "release. Opened by `.github/workflows/pin-bumps.yml`; the checks were started "
        "on this branch by that run (a PR opened with GITHUB_TOKEN starts none by "
        "itself). If they're missing, close and reopen the PR.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
