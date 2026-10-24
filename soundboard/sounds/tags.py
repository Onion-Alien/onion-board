"""Sound categories ("tags") and their "Category / Sub" subcategories: cleaning
names typed for them, matching them to the board's spelling, and which sounds a
Sounds tab view shows."""
from __future__ import annotations


SUB_SEP = " / "   # "Cat / Sub": the tag a sound in a subcategory carries (besides "Cat")
CATEGORY_MAX = 30   # characters in a category's (and a subcategory's) name
SOUND_NAME_MAX = 40   # ...and in a sound's


def split_tag(tag: str) -> tuple[str, str]:
    """("Cat", "Sub") for "Cat / Sub", ("Cat", "") for a plain category."""
    cat, sep, sub = tag.partition(SUB_SEP)
    return (cat, sub) if sep else (tag, "")


def sub_tag(cat: str, sub: str) -> str:
    return f"{cat}{SUB_SEP}{sub}"


def plain_name(name: str) -> str:
    """A name typed for a category or subcategory: on one line (tabs and line breaks
    are spaces), and one that can't be mistaken for a "Cat / Sub" tag."""
    return (clean_tags([one_line(name).replace(SUB_SEP, " - ")]) or [""])[0]


def one_line(name: str) -> str:
    """`name` with each run of spaces, tabs and line breaks as one space, trimmed."""
    return " ".join(str(name or "").split())


def clean_tags(tags) -> list[str]:
    """Category names: strings, trimmed, at most 30 characters, no duplicates
    (ignoring case), in order. A "Cat / Sub" tag keeps 30 characters of each part."""
    out, seen = [], set()
    for t in tags if isinstance(tags, list) else []:
        if not isinstance(t, str):
            continue
        cat, sub = split_tag(t.strip())
        cat, sub = cat.strip()[:CATEGORY_MAX].strip(), sub.strip()[:CATEGORY_MAX].strip()
        t = sub_tag(cat, sub) if cat and sub else cat
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out


def in_view(tags: list[str], cat: str, sub: str = "", hidden=()) -> bool:
    """Is a sound with `tags` on the Sounds tab showing `cat` (and its subcategory
    `sub`)? "" for `cat` is All: every sound but those in a `hidden` category."""
    if not cat:
        return not any(split_tag(t)[0] in hidden for t in tags)
    return (sub_tag(cat, sub) if sub else cat) in tags


def sub_names(tags: list[str], cat: str) -> list[str]:
    """The subcategories of `cat` that `tags` are in."""
    return [s for c, s in map(split_tag, tags) if s and c == cat]


def merge_tags(tags: list[str], categories: list[str],
               subs: dict | None = None) -> list[str]:
    """`tags` spelled the way `categories` already spells them (ignoring case), so an
    imported "memes" lands in the existing "Memes". Tags that aren't a category yet
    are appended to `categories`, which is changed in place. A "Cat / Sub" tag is no
    tab of its own: "Cat" is added (to the tags and `categories`) and, when `subs`
    is given, "Sub" is listed in it under "Cat"."""
    by_lower = {c.lower(): c for c in categories}

    def top(name: str) -> str:
        c = by_lower.get(name.lower())
        if c is None:
            categories.append(name)
            c = by_lower[name.lower()] = name
        return c

    out = []
    for t in clean_tags(tags):
        cat, sub = split_tag(t)
        cat = top(cat)
        if sub:
            known = subs.setdefault(cat, []) if subs is not None else []
            sub = {k.lower(): k for k in known}.get(sub.lower(), sub)
            if subs is not None and sub not in known:
                known.append(sub)
            out.append(cat)
            out.append(sub_tag(cat, sub))
        else:
            out.append(cat)
    return list(dict.fromkeys(out))


def group_pack_tags(sounds: list, pack_name: str, own: set[str] | None = None) -> bool:
    """A pack with several categories goes into one tab named after it, each of its
    categories a subcategory ("GM starter pack" with Tavern, Combat…) rather than a tab
    apiece: a sound's tags become [pack, "pack / category"]. `own` limits it to those
    categories (lower case), so a category the user added to a pack's sound stays as it
    is; None is every tag. Returns whether anything moved."""
    group = plain_name(pack_name)
    if not group:
        return False
    moved = False
    for m in sounds:
        tags, hit = [], False
        for t in m.tags:
            c, sub = split_tag(t)
            if sub or c.lower() == group.lower() or (own is not None and c.lower() not in own):
                tags.append(t)
            else:
                tags += [group, sub_tag(group, c)]
                hit = True
        if hit:
            m.tags = clean_tags(tags)
            moved = True
    return moved
