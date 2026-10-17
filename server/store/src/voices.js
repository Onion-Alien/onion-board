// Community voices: voice changer voices, AI voices and voice setups people share.
//
// A voice is a few hundred bytes of settings, never a file or a recording, and nobody's
// rights are in it, so it's on the store as soon as it's shared (no review). What makes
// that safe is that nothing sent is ever kept as sent: every field is checked against
// what the app can use and the voice is rebuilt from those checked fields alone
// (unknown keys dropped, every number finite and bounded, names one plain line of
// text). The app checks it all again when it takes a voice in (soundboard/storevoices.py).
// Enough reports from different addresses hide one until the owner looks at it.

export const KINDS = ["fx", "ai", "setup"];
export const MAX_NAME = 32;
export const MAX_ABOUT = 140;
const MAX_DATA = 4096;               // bytes of the rebuilt settings (a full voice is ~400)
const MAX_BODY = 16 << 10;           // bytes of the request it came in
const MAX_EFFECTS = 32;
const MAX_PARAMS = 24;
const MAX_LIVE = 50000;              // a full store refuses more (D1's free plan is 5 GB)
const SHARES_PER_DAY = 20;           // per install
const SHARES_PER_IP_DAY = 40;
const PAGE = 50;
const KEY_RE = /^[a-z][a-z0-9_]{0,23}$/;
const AI_ID_RE = /^[a-z0-9][a-z0-9-]{0,39}$/;
const LANG_RE = /^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})?$/;
// one emoji: a pictograph with at most a variation selector or a skin tone (no joined
// sequences, which only some fonts draw as one picture)
const EMOJI_RE = /^\p{Extended_Pictographic}(️)?(\p{Emoji_Modifier})?$/u;

// One line of plain text: Unicode-normalised, no control, format (bidi overrides,
// zero-width joiners), private-use or unpaired surrogate characters, none of <>`{}\
// (as a sound's name), at most two combining marks in a row (no "zalgo" text spilling
// over the lines around it), runs of spaces made one, cut to `max` characters (not
// halfway through a character).
export function plain(s, max) {
  let t = String(s ?? "").normalize("NFKC")
    .replace(/[\p{Cc}\p{Cf}\p{Co}\p{Cs}\p{Zl}\p{Zp}<>`{}\\]/gu, " ")
    .replace(/(\p{M}{2})\p{M}+/gu, "$1")
    .replace(/\s+/g, " ").trim();
  t = [...t].slice(0, max).join("").trim();
  return t;
}

function num(v, lo, hi) {
  return typeof v === "number" && Number.isFinite(v) ? Math.min(hi, Math.max(lo, v)) : null;
}

// {effect: {param: number}}: names the app's effects could have, finite numbers (each
// effect's own range is the app's to apply: it clamps every one to its slider)
function effects(raw) {
  if (raw === undefined) return {};
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const out = {};
  const keys = Object.keys(raw).sort();   // one order: the same voice is the same text
  if (keys.length > MAX_EFFECTS) return null;
  for (const k of keys) {
    const cfg = raw[k];
    if (!KEY_RE.test(k) || !cfg || typeof cfg !== "object" || Array.isArray(cfg)) return null;
    const ps = Object.keys(cfg).sort();
    if (ps.length > MAX_PARAMS) return null;
    const d = {};
    for (const p of ps) {
      const v = num(cfg[p], -1e6, 1e6);
      if (!KEY_RE.test(p) || v === null) return null;
      d[p] = Math.round(v * 1e4) / 1e4;
    }
    out[k] = d;
  }
  return out;
}

// an AI voice's blend: 1-4 [speaker, weight] pairs, a formant and a pitch
function blend(raw) {
  if (!raw || typeof raw !== "object" || !Array.isArray(raw.mix)) return null;
  if (!raw.mix.length || raw.mix.length > 4) return null;
  const mix = [];
  for (const m of raw.mix) {
    if (!Array.isArray(m) || m.length !== 2 || !Number.isInteger(m[0]) || m[0] < 0 || m[0] > 9999)
      return null;
    const w = num(m[1], 0, 1);
    if (w === null || w <= 0) return null;
    mix.push([m[0], Math.round(w * 1e4) / 1e4]);
  }
  const formant = num(raw.formant ?? 0, -2, 2);
  const hz = num(raw.pitch_hz, 60, 400);
  if (formant === null || hz === null) return null;
  return { mix, formant, pitch_hz: hz };
}

// The settings rebuilt from checked fields only, or null when they can't be a voice.
//   fx:    {"e": effects}
//   ai:    {"mix", "formant", "pitch_hz"}
//   setup: {"e"?, "fx"?, "ai"? {"id", "name", "pitch", + a blend when it's someone's own},
//           "lang"?}: at least one part
export function rebuild(kind, raw) {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  if (kind === "fx") {
    const e = effects(raw.e);
    return e && Object.keys(e).length ? { e } : null;
  }
  if (kind === "ai") return blend(raw);
  if (kind !== "setup") return null;
  const out = {};
  const e = effects(raw.e);
  if (e === null) return null;
  if (Object.keys(e).length) {
    out.e = e;
    const fx = plain(raw.fx, MAX_NAME);
    if (fx) out.fx = fx;
  }
  if (raw.ai !== undefined) {
    const a = raw.ai;
    if (!a || typeof a !== "object" || !AI_ID_RE.test(String(a.id ?? ""))) return null;
    const pitch = num(a.pitch ?? 0, -12, 12);
    if (pitch === null) return null;
    out.ai = { id: a.id, name: plain(a.name, MAX_NAME) || a.id, pitch };
    if (a.mix !== undefined) {
      const b = blend(a);
      if (!b) return null;
      Object.assign(out.ai, b);
    }
  }
  if (raw.lang !== undefined && raw.lang !== "") {
    if (!LANG_RE.test(String(raw.lang))) return null;
    out.lang = raw.lang;
  }
  return Object.keys(out).length ? out : null;
}

function shown(r) {
  return { id: r.id, kind: r.kind, name: r.name, about: r.about, emoji: r.emoji,
           tags: r.tags ? r.tags.split(",") : [], data: JSON.parse(r.data),
           up: r.up, down: r.down, created: r.created,
           ...(r.mine !== undefined ? { mine: r.mine || 0 } : {}) };
}

// ------------------------------------------------------------------ routes

export async function voicesRoute(req, env, url, p, t) {
  const m = req.method;
  let g;
  if (p === "/v1/voices" && m === "GET") return list(url, req, env, t);
  if (p === "/v1/voices" && m === "POST") return share(req, env, t);
  if ((g = p.match(/^\/v1\/voices\/([0-9a-f]{12})\/vote$/)) && m === "POST")
    return t.vote(req, env, g[1], "voices");
  if ((g = p.match(/^\/v1\/voices\/([0-9a-f]{12})\/report$/)) && m === "POST")
    return t.report(req, env, g[1], "voices");
  return null;
}

export async function adminVoicesRoute(req, env, url, p, t) {
  const m = req.method;
  let g;
  if (p === "/v1/admin/voices" && m === "GET") {
    const status = ["live", "hidden", "removed"].includes(url.searchParams.get("status"))
      ? url.searchParams.get("status") : "hidden";
    const rows = await env.DB.prepare("SELECT * FROM voices WHERE status = ? " +
      "ORDER BY reports DESC, created DESC LIMIT 200").bind(status).all();
    return t.json({ voices: (rows.results || []).map(r => ({ ...shown(r), status: r.status,
                                                          reports: r.reports })) });
  }
  if ((g = p.match(/^\/v1\/admin\/voices\/([0-9a-f]{12})$/)) && m === "POST") {
    const { action } = await t.body(req);
    if (!["live", "removed"].includes(action)) t.fail("action");
    const row = await env.DB.prepare("SELECT name FROM voices WHERE id = ?").bind(g[1]).first();
    if (!row) t.fail("not found", 404);
    await env.DB.prepare("UPDATE voices SET status = ? WHERE id = ?").bind(action, g[1]).run();
    if (action === "live")    // back on: the reports that hid it are done with
      await env.DB.prepare("DELETE FROM reports WHERE sound = ?").bind(g[1]).run();
    await t.logAction(env, action === "live" ? "approve" : "reject",
                      { sound: g[1], ip: "owner", detail: row.name });
    return t.json({ id: g[1], status: action });
  }
  return null;
}

async function list(url, req, env, t) {
  const sort = ["new", "trending"].includes(url.searchParams.get("sort"))
    ? url.searchParams.get("sort") : "top";
  const kind = url.searchParams.get("kind") || "";
  const q = plain(url.searchParams.get("q"), 60).toLowerCase();
  const offset = Math.max(0, Math.min(10000, parseInt(url.searchParams.get("offset")) || 0));
  const voter = await t.installHash(req, env, false);
  const where = ["v.status = 'live'"];
  const args = [];
  if (KINDS.includes(kind)) { where.push("v.kind = ?"); args.push(kind); }
  if (q) {
    for (const word of q.split(" ").slice(0, 5)) {
      where.push("(lower(v.name) LIKE ? ESCAPE '\\' OR v.tags LIKE ? ESCAPE '\\' " +
                 "OR lower(v.about) LIKE ? ESCAPE '\\')");
      const like = `%${word.replace(/[\\%_]/g, c => "\\" + c)}%`;
      args.push(like, like, like);
    }
  }
  const order = sort === "new" ? "v.created DESC"
    : sort === "trending" ? "v.likes DESC, (v.up - v.down) DESC, v.created DESC"
    : "(v.up - v.down) DESC, v.up DESC, v.created DESC";   // each as an index in schema.sql
  const mine = voter ? ", (SELECT value FROM votes x WHERE x.sound = v.id AND x.voter = ?) AS mine" : "";
  const rows = await env.DB.prepare(`SELECT v.*${mine} FROM voices v WHERE ${where.join(" AND ")} ` +
                                    `ORDER BY ${order} LIMIT ? OFFSET ?`)
    .bind(...(voter ? [voter] : []), ...args, PAGE + 1, offset).all();
  const res = rows.results || [];
  return t.json({ voices: res.slice(0, PAGE).map(shown), more: res.length > PAGE });
}

async function share(req, env, t) {
  if (parseInt(req.headers.get("content-length") || "0") > MAX_BODY) t.fail("too big", 413);
  const textIn = await req.text();
  if (textIn.length > MAX_BODY) t.fail("too big", 413);
  let raw;
  try {
    raw = JSON.parse(textIn);
  } catch {
    t.fail("json");
  }
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) t.fail("json");
  const kind = KINDS.includes(raw.kind) ? raw.kind : "";
  if (!kind) t.fail("kind");
  const name = plain(raw.name, MAX_NAME);
  if (!name) t.fail("name");
  const about = plain(raw.about, MAX_ABOUT);
  const blocked = String(env.CHAT_BLOCK || "").split(",");
  for (const text of [name, about, t.cleanTags(raw.tags)])
    if (text && t.refuse(text.slice(0, 200), blocked)) t.fail("not allowed", 422);
  const emoji = EMOJI_RE.test(String(raw.emoji ?? "")) ? raw.emoji : "";
  const data = rebuild(kind, raw.data);
  if (!data) t.fail("not a voice", 422);
  const text = JSON.stringify(data);
  if (new TextEncoder().encode(text).length > MAX_DATA) t.fail("too big", 413);
  // the same settings can't be shared twice (a renamed copy isn't a new voice)
  const hash = await t.sha256(`voice:${kind}:${text}`);
  const same = await env.DB.prepare("SELECT id FROM voices WHERE sha256 = ?").bind(hash).first();
  if (same) return t.json({ error: "duplicate", id: same.id }, 409);
  const live = (await env.DB.prepare("SELECT count(*) AS n FROM voices").first()).n;
  if (live >= MAX_LIVE) t.fail("store full", 503);
  const uploader = await t.installHash(req, env);
  const ip = await t.ipHash(req, env);
  if (!await t.allow(env, "voice", uploader, SHARES_PER_DAY)
      || !await t.allow(env, "voice-ip", ip, SHARES_PER_IP_DAY)) t.fail("slow down", 429);
  const id = (await t.sha256(crypto.randomUUID())).slice(0, 12);
  await env.DB.prepare("INSERT INTO voices (id, kind, name, about, emoji, tags, data, sha256, " +
    "uploader, ip, created) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")
    .bind(id, kind, name, about, emoji, t.cleanTags(raw.tags), text, hash, uploader, ip, t.now())
    .run();
  await t.logAction(env, "voice", { sound: id, ip, install: uploader, detail: `${kind}: ${name}` });
  return t.json({ id, status: "live" }, 201);
}
