// Talking to Onion Board's control API (Settings → Remote in the app), and drawing the keys.
// No Stream Deck code in here, so the tests can run it on its own (streamdeck/test/).
import { readFile, stat } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";

export const DEFAULT_PORT = 7474;
export const TIMEOUT_MS = 2500;
export const SITE = "https://onionalien.com/onionboard/";

// what can go wrong, in the order a user would fix it
export const PROBLEMS = {
  no_app: "Onion Board isn't installed on this PC (or hasn't been opened yet).",
  remote_off: "In Onion Board, turn on Settings → Remote → Remote control.",
  not_running: "Onion Board isn't running. Open it and this key works again.",
  bad_key: "Onion Board refused the key. If you typed one under Connect by hand, copy it again from Settings → Remote.",
  error: "Onion Board couldn't do that.",
};

export function configPath(env = process.env) {
  const appdata = env.APPDATA || join(homedir(), "AppData", "Roaming");
  return join(appdata, "OnionBoard", "config.json");
}

// Where the API listens and its key, from Onion Board's own config.json (read only;
// the app owns that file). null: there's no config.json (the app was never opened).
export async function readConnection(path = configPath()) {
  let text;
  try {
    text = await readFile(path, "utf8");
  } catch {
    return null;
  }
  let cfg;
  try {
    cfg = JSON.parse(text.replace(/^﻿/, ""));
  } catch {
    return null;   // half-written while the app saves: the next try reads it
  }
  const port = Number.isInteger(cfg.api_port) && cfg.api_port > 0 && cfg.api_port < 65536
    ? cfg.api_port : DEFAULT_PORT;
  return { enabled: cfg.api_enabled === true, port,
           token: typeof cfg.api_token === "string" ? cfg.api_token : "" };
}

// One request to the API: { ok, status, body, problem }; never throws.
export class OnionBoard {
  constructor({ path = configPath(), fetch = globalThis.fetch, timeoutMs = TIMEOUT_MS } = {}) {
    this.path = path;
    this.fetch = fetch;
    this.timeoutMs = timeoutMs;
    this.manual = null;     // { port, token } typed under "Connect by hand"
    this.cached = null;     // the connection read from config.json…
    this.mtime = -1;        // …when the file looked like this
  }

  setManual(settings) {
    const token = String(settings?.token || "").trim();
    const port = Number.parseInt(settings?.port, 10);
    this.manual = token ? { enabled: true, token,
                            port: port > 0 && port < 65536 ? port : DEFAULT_PORT } : null;
  }

  async connection() {
    if (this.manual) return this.manual;
    let mtime;
    try {
      mtime = (await stat(this.path)).mtimeMs;
    } catch {
      this.cached = null;
      this.mtime = -1;
      return null;
    }
    if (mtime !== this.mtime || this.cached === null) {
      this.cached = await readConnection(this.path);
      this.mtime = this.cached ? mtime : -1;
    }
    return this.cached;
  }

  async call(action, params = {}) {
    const conn = await this.connection();
    if (!conn) return { ok: false, status: 0, body: null, problem: "no_app" };
    if (!conn.enabled || !conn.token) return { ok: false, status: 0, body: null, problem: "remote_off" };
    const query = new URLSearchParams(params).toString();
    const url = `http://127.0.0.1:${conn.port}/api/${action}${query ? `?${query}` : ""}`;
    let res;
    try {
      res = await this.fetch(url, { headers: { "X-Token": conn.token },
                                    signal: AbortSignal.timeout(this.timeoutMs) });
    } catch {
      return { ok: false, status: 0, body: null, problem: "not_running" };
    }
    let body = null;
    try {
      body = await res.json();
    } catch {
      // not JSON: something else is on that port
    }
    if (res.status === 401) {
      this.mtime = -1;   // the key changed in Settings: read it again next time
      return { ok: false, status: 401, body, problem: "bad_key" };
    }
    return { ok: res.ok, status: res.status, body, problem: res.ok ? null : "error" };
  }
}

// --------------------------------------------------------------------------- the keys

// A sound's name over up to three lines that fit a key (Stream Deck doesn't wrap titles).
export function keyTitle(name, width = 9, lines = 3) {
  const words = String(name || "").trim().split(/\s+/).filter(Boolean);
  const out = [];
  for (let word of words) {
    while (word.length > width) {   // a long word: split it over lines
      const last = out.length ? out[out.length - 1] : null;
      const room = last === null ? 0 : width - last.length - 1;
      if (room >= 3) {
        out[out.length - 1] = `${last} ${word.slice(0, room)}`;
        word = word.slice(room);
      } else {
        out.push(word.slice(0, width));
        word = word.slice(width);
      }
    }
    if (!word) continue;
    const last = out.length ? out[out.length - 1] : null;
    if (last !== null && last.length + 1 + word.length <= width) out[out.length - 1] = `${last} ${word}`;
    else out.push(word);
  }
  if (out.length > lines) {
    out.length = lines;
    out[lines - 1] = `${out[lines - 1].slice(0, width - 1)}…`;
  }
  return out.join("\n");
}

const HEX = /^#[0-9a-f]{6}$/i;

function shade(hex, f) {   // f < 1 darker, f > 1 lighter
  const n = Number.parseInt(hex.slice(1), 16);
  const c = [n >> 16, (n >> 8) & 255, n & 255].map((v) => {
    const out = f < 1 ? v * f : v + (255 - v) * (f - 1);
    return Math.max(0, Math.min(255, Math.round(out)));
  });
  return `#${c.map((v) => v.toString(16).padStart(2, "0")).join("")}`;
}

function svgUrl(svg) {
  return `data:image/svg+xml;charset=utf8,${encodeURIComponent(svg)}`;
}

// A Play sound key: the pad's colour, dimmed; full colour with a white ring while it plays,
// grey with a "!" when Onion Board can't be reached. The name is the key's title.
export function soundImage({ color = "#7c5cff", playing = false, problem = null } = {}) {
  const base = problem ? "#5a5a66" : (HEX.test(color) ? color : "#7c5cff");
  const fill = playing ? base : shade(base, 0.55);
  const wave = playing ? "#ffffff" : shade(base, 1.6);
  const ring = playing
    ? '<rect x="4" y="4" width="136" height="136" rx="22" fill="none" stroke="#ffffff" stroke-width="8"/>'
    : "";
  const badge = problem
    ? '<circle cx="114" cy="30" r="20" fill="#ff5c5c"/><rect x="111" y="16" width="6" height="18" rx="3" fill="#fff"/><circle cx="114" cy="41" r="3.5" fill="#fff"/>'
    : "";
  return svgUrl(
    '<svg xmlns="http://www.w3.org/2000/svg" width="144" height="144" viewBox="0 0 144 144">'
    + `<rect width="144" height="144" rx="26" fill="${fill}"/>${ring}`
    // a small sound wave near the top, so the title has the middle and bottom
    + `<g fill="${wave}"><rect x="46" y="30" width="8" height="20" rx="4"/>`
    + '<rect x="60" y="20" width="8" height="40" rx="4"/><rect x="74" y="26" width="8" height="28" rx="4"/>'
    + `<rect x="88" y="33" width="8" height="14" rx="4"/></g>${badge}</svg>`);
}

// the switches a Toggle key can be, and what /api/status calls each
export const TOGGLES = {
  live: { label: "Live / Muted", on: "Live", off: "Muted" },
  voice: { label: "Voice changer", on: "Voice\non", off: "Voice\noff" },
  mic: { label: "Others hear my mic", on: "Mic\non", off: "Mic\noff" },
  hotkeys: { label: "Hotkeys", on: "Hotkeys\non", off: "Hotkeys\noff" },
};
