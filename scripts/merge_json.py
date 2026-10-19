"""Git merge driver for the translation catalogs (`assets/lang/*.json`).

`scripts/checks/i18n_extract.py --update` adds every new text at the end of each catalog, so
two branches that both add texts always clash on the last lines of all of them, though
they never touch the same text. This merges by key instead: a text added on either
side is kept (ours first, then theirs in their order), a translation changed on one
side wins, a text removed on one side and untouched on the other goes. Only the same
text changed differently on both sides is a real conflict: then it leaves ours, lists
the texts and exits 1, so git marks the file conflicted.

Turned on by `.gitattributes` (`merge=langjson`) plus this, which `scripts\\precommit.ps1`
sets in every checkout and `scripts/merge_pr.sh` passes itself:

    git config merge.langjson.driver "python scripts/merge_json.py %O %A %B"

Without it git falls back to its line merge. Standard library only.
"""
import json
import sys
from pathlib import Path

_GONE = object()


def merge(base: dict, ours: dict, theirs: dict) -> tuple[dict, list[str]]:
    """The by-key three-way merge: (result, the keys both sides changed differently)."""
    out, clashes = {}, []
    for key in [*ours, *(k for k in theirs if k not in ours)]:
        o, a, b = base.get(key, _GONE), ours.get(key, _GONE), theirs.get(key, _GONE)
        if a == b:
            v = a
        elif a == o:
            v = b
        elif b == o:
            v = a
        else:
            clashes.append(key)
            v = a
        if v is not _GONE:
            out[key] = v
    return out, clashes


def main(argv: list[str]) -> int:
    base_p, ours_p, theirs_p = (Path(p) for p in argv[1:4])
    raw = ours_p.read_bytes()
    try:
        base, ours, theirs = (json.loads(p.read_text(encoding="utf-8") or "{}")
                              for p in (base_p, ours_p, theirs_p))
    except (ValueError, UnicodeDecodeError) as e:
        print(f"merge_json: not JSON ({e}); merge {ours_p} by hand", file=sys.stderr)
        return 1
    if not all(isinstance(d, dict) for d in (base, ours, theirs)):
        print("merge_json: not a JSON object; merge it by hand", file=sys.stderr)
        return 1
    out, clashes = merge(base, ours, theirs)
    if clashes:
        print("merge_json: changed differently on both sides: "
              + ", ".join(repr(k) for k in clashes[:10]), file=sys.stderr)
        return 1
    text = json.dumps(out, ensure_ascii=False, indent=2) + "\n"
    if b"\r\n" in raw:
        text = text.replace("\n", "\r\n")
    ours_p.write_bytes(text.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
