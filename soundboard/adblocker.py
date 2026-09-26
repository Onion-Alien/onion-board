"""Ad blocking for the browser tab.

Network requests go through Brave's adblock engine (the `adblock` package: Python
bindings for adblock-rust) loaded with the same lists uBlock Origin ships with
(EasyList, EasyPrivacy, uBlock filters). The lists are downloaded in the background,
compiled once and cached in the browser folder, and refreshed every few days; until
they arrive (or if there's no internet) a small built-in list covers the ad servers.

YouTube serves its video ads from the same servers as the videos, so blocking
requests can't stop them. YOUTUBE_JS does what uBlock Origin's json-prune scriptlets
do: it strips the ad fields out of the player's data before the player reads them.
If an ad gets through anyway it's muted, fast-forwarded and skipped, so it never
reaches the mic.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.request
from pathlib import Path

from PySide6.QtWebEngineCore import QWebEngineUrlRequestInfo, QWebEngineUrlRequestInterceptor

try:
    import adblock
except ImportError:   # optional: without it only the YouTube script runs
    adblock = None

log = logging.getLogger(__name__)

FILTER_LISTS = (
    ("easylist", "https://easylist.to/easylist/easylist.txt"),
    ("easyprivacy", "https://easylist.to/easylist/easyprivacy.txt"),
    ("ublock", "https://ublockorigin.github.io/uAssets/filters/filters.txt"),
    ("ublock-privacy", "https://ublockorigin.github.io/uAssets/filters/privacy.txt"),
)
REFRESH_S = 4 * 24 * 3600
ENGINE_FILE = "engine.dat"

# used until the real lists are ready
BUILTIN_FILTERS = """
||doubleclick.net^
||googlesyndication.com^
||googleadservices.com^
||google-analytics.com^
||googletagmanager.com^
||googletagservices.com^
||adservice.google.com^
||imasdk.googleapis.com^
||youtube.com/pagead/
||youtube.com/api/stats/ads
||youtube.com/ptracking
||youtube.com/get_midroll_
||amazon-adsystem.com^
||adnxs.com^
||taboola.com^
||outbrain.com^
||criteo.com^
||criteo.net^
||pubmatic.com^
||rubiconproject.com^
||scorecardresearch.com^
"""

_R = QWebEngineUrlRequestInfo.ResourceType
# Qt resource type -> the request type names adblock filters use
_TYPES = {}
for _qt, _name in (
        ("ResourceTypeSubFrame", "subdocument"), ("ResourceTypeStylesheet", "stylesheet"),
        ("ResourceTypeScript", "script"), ("ResourceTypeImage", "image"),
        ("ResourceTypeFontResource", "font"), ("ResourceTypeObject", "object"),
        ("ResourceTypeMedia", "media"), ("ResourceTypeWorker", "script"),
        ("ResourceTypeSharedWorker", "script"), ("ResourceTypeServiceWorker", "script"),
        ("ResourceTypeFavicon", "image"), ("ResourceTypeXhr", "xmlhttprequest"),
        ("ResourceTypePing", "ping"), ("ResourceTypeCspReport", "csp_report"),
        ("ResourceTypePluginResource", "object"), ("ResourceTypeWebSocket", "websocket"),
        ("ResourceTypeJson", "xmlhttprequest")):
    if hasattr(_R, _qt):
        _TYPES[getattr(_R, _qt)] = _name


def _engine_from(text: str):
    fs = adblock.FilterSet()
    fs.add_filter_list(text)
    return adblock.Engine(fs)


class AdBlocker(QWebEngineUrlRequestInterceptor):
    """Blocks ad and tracker requests for a web profile.

    Starts on the built-in list at once, then swaps in the full engine from a
    background thread (a plain attribute swap, so no locking is needed)."""

    def __init__(self, store: Path, parent=None, update=True):
        super().__init__(parent)
        self.store = Path(store)
        self.blocked = 0
        self._engine = _engine_from(BUILTIN_FILTERS) if adblock else None
        if adblock is None:
            log.warning("adblock package missing: only YouTube ads are blocked")
        elif update:
            threading.Thread(target=self._load, name="adblock-lists", daemon=True).start()

    @property
    def available(self) -> bool:
        return self._engine is not None

    def should_block(self, url: str, source: str, rtype: str) -> bool:
        e = self._engine
        if e is None or not url.startswith(("http:", "https:", "ws:", "wss:")):
            return False
        try:
            return e.check_network_urls(url, source or url, rtype).matched
        except Exception:   # noqa: BLE001 - a filter quirk must never break a page load
            return False

    def interceptRequest(self, info: QWebEngineUrlRequestInfo):
        rtype = _TYPES.get(info.resourceType())
        if rtype is None:   # the page itself, prefetches and the like are never blocked
            return
        if self.should_block(info.requestUrl().toString(), info.firstPartyUrl().toString(),
                             rtype):
            info.block(True)
            self.blocked += 1

    def hide_css(self, url: str) -> str:
        """Element-hiding rules (##selector) for a page, as a stylesheet."""
        e = self._engine
        if e is None:
            return ""
        try:
            sel = e.url_cosmetic_resources(url).hide_selectors
        except Exception:   # noqa: BLE001
            return ""
        return ",".join(sel) + "{display:none!important}" if sel else ""

    # ------------------------------------------------------------------ lists
    def _load(self):
        try:
            self.store.mkdir(parents=True, exist_ok=True)
            cached = self.store / ENGINE_FILE
            fresh = cached.exists() and time.time() - cached.stat().st_mtime < REFRESH_S
            if cached.exists() and self._load_cached(cached) and fresh:
                return
            if self._rebuild():
                self._engine.serialize_to_file(str(cached))
        except Exception:   # noqa: BLE001
            log.exception("ad block lists couldn't be loaded")

    def _load_cached(self, path: Path) -> bool:
        try:
            e = adblock.Engine(adblock.FilterSet())
            e.deserialize_from_file(str(path))
        except Exception:   # noqa: BLE001 - an old or broken cache is just rebuilt
            log.info("ad block cache unreadable, rebuilding")
            return False
        self._engine = e
        return True

    def _rebuild(self) -> bool:
        texts, got = [BUILTIN_FILTERS], 0
        for name, url in FILTER_LISTS:
            path = self.store / f"{name}.txt"
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Soundboard"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    data = r.read().decode("utf-8", "replace")
                path.write_text(data, encoding="utf-8")
                got += 1
            except Exception as e:   # noqa: BLE001 - offline: fall back to the last copy
                log.info("couldn't download %s (%s)", name, e)
                if not path.exists():
                    continue
                data = path.read_text(encoding="utf-8", errors="replace")
            texts.append(data)
        if len(texts) == 1:
            return False
        self._engine = _engine_from("\n".join(texts))
        log.info("ad block engine ready (%d lists, %d fresh)", len(texts) - 1, got)
        return got > 0


# Runs in the page's own JS world on youtube.com, from document creation, so it's in
# place before the player reads its config. Like uBlock Origin's json-prune and
# set-constant scriptlets, it removes the ad fields from every player response
# (inline ytInitialPlayerResponse, JSON.parse, fetch().json()). Fallback: while the
# player is in ad mode the video is muted, sped up, jumped to its end and skipped;
# the "ad blockers aren't allowed" popup is removed.
YOUTUBE_JS = r"""
(function () {
  if (window.__sbAds) return;
  window.__sbAds = true;
  if (!/(^|\.)youtube(-nocookie)?\.com$/.test(location.hostname)) return;

  const KEYS = ['adPlacements', 'adSlots', 'playerAds', 'adBreakHeartbeatParams'];
  function prune(o) {
    if (!o || typeof o !== 'object') return o;
    for (const k of KEYS) if (k in o) delete o[k];
    if (o.playerResponse) prune(o.playerResponse);
    if (Array.isArray(o)) o.forEach(x => x && x.playerResponse && prune(x.playerResponse));
    return o;
  }

  const parse = JSON.parse;
  JSON.parse = function () {
    const r = parse.apply(this, arguments);
    try { prune(r); } catch (e) {}
    return r;
  };
  const json = Response.prototype.json;
  Response.prototype.json = function () {
    return json.apply(this, arguments).then(r => { try { prune(r); } catch (e) {} return r; });
  };
  for (const name of ['ytInitialPlayerResponse', 'playerResponse']) {
    let v;
    try {
      Object.defineProperty(window, name, {
        configurable: true,
        get() { return v; },
        set(x) { v = prune(x); },
      });
    } catch (e) {}
  }

  // fallback: an ad got through
  let saved = null;   // the video's own muted/rate, restored after the ad
  const SKIP = '.ytp-skip-ad-button, .ytp-ad-skip-button, .ytp-ad-skip-button-modern, '
             + '.ytp-ad-overlay-close-button';
  setInterval(() => {
    const p = document.getElementById('movie_player');
    const v = p && p.querySelector('video');
    const inAd = !!p && (p.classList.contains('ad-showing')
                         || p.classList.contains('ad-interrupting'));
    if (inAd && v) {
      if (!saved) saved = {muted: v.muted, rate: v.playbackRate};
      v.muted = true;
      v.playbackRate = 16;
      if (isFinite(v.duration) && v.duration > 0) v.currentTime = v.duration;
      document.querySelectorAll(SKIP).forEach(b => b.click());
    } else if (saved && v) {
      v.muted = saved.muted;
      v.playbackRate = saved.rate;
      saved = null;
    }
    document.querySelectorAll('ytd-enforcement-message-view-model').forEach(m => {
      const d = m.closest('tp-yt-paper-dialog');
      (d || m).remove();
      document.querySelectorAll('tp-yt-iron-overlay-backdrop').forEach(b => b.remove());
      if (v && v.paused) v.play();
    });
  }, 250);
})();
"""


def hide_css_js(css: str) -> str:
    """Adds (or replaces) the page's element-hiding stylesheet."""
    return ("(()=>{let s=document.getElementById('sb-adhide');"
            "if(!s){s=document.createElement('style');s.id='sb-adhide';"
            "(document.head||document.documentElement).appendChild(s)}"
            f"s.textContent={json.dumps(css)}}})()")
