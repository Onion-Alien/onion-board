"""The Radio tab map's data for soundboard.online.radio: the shipped country outlines
(checked by their hash) and their labels, each station's dot and the town names."""
from __future__ import annotations

import base64
import hashlib
import json
from soundboard.online.radiostation import COUNTRIES_SRI, COUNTRY_NAMES, PLACES, Station


def _outline_features(raw: bytes) -> list[tuple[dict, list[list[tuple[float, float]]]]]:
    """(properties, outer rings as (lon, lat)) per country, or [] unless `raw` is
    exactly the pinned outline file (checked by its hash)."""
    if not isinstance(raw, bytes | bytearray):
        return []
    digest = "sha384-" + base64.b64encode(hashlib.sha384(raw).digest()).decode()
    if digest != COUNTRIES_SRI:
        return []
    try:
        features = json.loads(raw)["features"]
    except (ValueError, KeyError, TypeError):
        return []
    out = []
    for f in features:
        g = f.get("geometry") or {}
        polys = ([g.get("coordinates")] if g.get("type") == "Polygon"
                 else g.get("coordinates") if g.get("type") == "MultiPolygon" else [])
        rings = [[(float(x), float(y)) for x, y, *_ in poly[0]]
                 for poly in polys or [] if poly and len(poly[0]) >= 3]
        if rings:
            out.append((f.get("properties") or {}, rings))
    return out


def outline_rings(raw: bytes) -> list[list[tuple[float, float]]]:
    """The land outlines for the flat map: each country's outer rings as (lon, lat), or
    [] unless `raw` is exactly the pinned outline file."""
    return [r for _props, rings in _outline_features(raw) for r in rings]


def _centre(ring: list[tuple[float, float]]) -> tuple[float, float, float]:
    """A ring's centroid (lon, lat) and its area (shoelace, in square degrees)."""
    a = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]):
        k = x0 * y1 - x1 * y0
        a += k
        cx += (x0 + x1) * k
        cy += (y0 + y1) * k
    if abs(a) < 1e-9:
        xs, ys = [p[0] for p in ring], [p[1] for p in ring]
        return sum(xs) / len(xs), sum(ys) / len(ys), 0.0
    return cx / (3 * a), cy / (3 * a), abs(a) / 2


def outline_labels(raw: bytes) -> list[tuple[str, float, float, float]]:
    """Names for the flat map: (name, lon, lat, width in degrees) per country, on its
    biggest piece of land, plus the small places the outlines leave out (PLACES).
    [] unless `raw` is the pinned outline file."""
    out = []
    for props, rings in _outline_features(raw):
        name = str(props.get("NAME") or props.get("ADMIN") or "")
        name = COUNTRY_NAMES.get(name, name)
        if not name:
            continue
        ring = max(rings, key=lambda r: _centre(r)[2])
        lon, lat, _a = _centre(ring)
        xs = [p[0] for p in ring]
        out.append((name, lon, lat, max(xs) - min(xs)))
    if out:
        out += [(name, lon, lat, w) for name, lat, lon, w in PLACES]
    return out


# --------------------------------------------------------------------------- the map

def globe_points(stations: list[Station]) -> list[dict]:
    """What the map needs per station (short keys; the name is from the old globe).
    The dicts are each station's own, made once: read them, don't change them."""
    return [s.map_point for s in stations if s.lat is not None and s.lon is not None]


TOWNS_MAX = 600            # city and town names the maps get (each shows only zoomed in)
TOWN_SPREAD = 3.0          # a place's stations this far (degrees) from its middle are strays


def _median(values) -> float:
    """statistics.median, without its overhead: town_labels takes thousands of them."""
    v = sorted(values)
    i = len(v) // 2
    return v[i] if len(v) % 2 else (v[i - 1] + v[i]) / 2


def town_labels(points: list[dict], limit: int = TOWNS_MAX) -> list[dict]:
    """Cities, towns and regions to name on the maps when zoomed in, from the stations'
    own place field ("s"): {"n": name, "la", "lo": where its stations are (median),
    "k": how many}, the places with the most stations first. Only places that have
    stations are named, so a name always has dots to click around it."""
    groups: dict[tuple[str, str], list[dict]] = {}
    for d in points:
        name = " ".join(str(d.get("s") or "").split())
        if not 2 <= len(name) <= 40 or not any(ch.isalpha() for ch in name):
            continue
        country = str(d.get("c") or "").strip().casefold()
        if name.casefold() in (country, str(d.get("cc") or "").casefold()):
            continue   # "France, France": the map already names the country
        groups.setdefault((name.casefold(), str(d.get("cc") or "")), []).append(d)
    out = []
    for members in groups.values():
        # a place on the 180° line (Fiji, Chukotka) has stations at 179.9 and -179.9:
        # take its middle with the west side moved round, so they're neighbours
        lons = [d["lo"] for d in members]
        wrap = max(lons) - min(lons) > 180
        lon = (lambda d: d["lo"] + 360 if d["lo"] < 0 else d["lo"]) if wrap else \
            (lambda d: d["lo"])
        la = _median(d["la"] for d in members)
        lo = _median(lon(d) for d in members)
        near = [d for d in members
                if abs(d["la"] - la) <= TOWN_SPREAD and abs(lon(d) - lo) <= TOWN_SPREAD]
        if len(near) < max(1, len(members) / 2):
            continue   # scattered all over: the name doesn't belong to one spot
        spellings: dict[str, int] = {}
        for d in near:
            n = " ".join(str(d["s"]).split())
            spellings[n] = spellings.get(n, 0) + 1
        # the most used spelling; on a tie, a capitalised one ("Accra" over "accra")
        name = max(spellings, key=lambda n: (spellings[n], n[:1].isupper(), n))
        mid = _median(lon(d) for d in near)
        out.append({"n": name, "la": round(_median(d["la"] for d in near), 4),
                    "lo": round(mid - 360 if mid > 180 else mid, 4), "k": len(near)})
    out.sort(key=lambda t: (-t["k"], t["n"]))
    return out[:limit]
