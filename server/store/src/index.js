// The sound store's server: a Cloudflare Worker with the sounds' files in Workers KV
// and the list, votes and reports in D1 (both on the free plan, no card needed). Onion Board's Store tab (soundboard/store.py) talks
// to the /v1 routes; the owner approves uploads on /admin.
//
// Nothing here knows who anyone is. The app sends a random install id it made itself
// (X-Onion-Install); it's kept only as a salted hash, so one install gets one vote per
// sound. Addresses are kept the same way, only to stop one address flooding the store.
import { ADMIN_PAGE } from "./admin.js";
import { chatRoute } from "./chat.js";

export { ChatRoom } from "./chat.js";   // the Durable Object wrangler.toml names

const MAX_BYTES = 4 << 20;          // the biggest sound accepted (4 MB)
const PAGE = 50;                     // sounds per list page
const UPLOADS_PER_DAY = 10;          // per install
const UPLOADS_PER_IP_DAY = 20;
const VOTES_PER_IP_DAY = 400;
const REPORTS_TO_HIDE = 3;           // reports from different installs: back to review
const PENDING_CAP = 1000;            // a full review queue refuses new uploads
const AGREEMENT = "own-cc0-v1";      // the version of the upload agreement accepted
const LINK_AGREEMENT = "link-v1";    // a shared link: only the link is kept
// the sites a link may point at (as the app's soundboard/sourceinfo.py): never a file host
const LINK_SITES = ["youtube.com", "youtu.be", "music.youtube.com", "tiktok.com",
  "soundcloud.com", "instagram.com", "twitter.com", "x.com", "reddit.com", "twitch.tv",
  "vimeo.com", "bandcamp.com", "myinstants.com", "streamable.com", "dailymotion.com"];
const ID_RE = /^[0-9a-f]{12}$/;
const INSTALL_RE = /^[0-9a-f-]{16,64}$/;
const TYPES = { mp3: "audio/mpeg", ogg: "audio/ogg", wav: "audio/wav", flac: "audio/flac" };

export default {
  async fetch(req, env) {
    try {
      return await route(req, env);
    } catch (e) {
      if (e instanceof Answer) return e.response;
      console.error(e && e.stack || e);
      return json({ error: "server" }, 500);
    }
  },
};

class Answer extends Error {
  constructor(response) { super("answer"); this.response = response; }
}

function json(body, status = 200, headers = {}) {
  return new Response(JSON.stringify(body), {
    status, headers: { "content-type": "application/json; charset=utf-8",
                       "cache-control": "no-store", ...headers },
  });
}

function fail(error, status = 400) { throw new Answer(json({ error }, status)); }

async function route(req, env) {
  const url = new URL(req.url);
  const p = url.pathname.replace(/\/+$/, "") || "/";
  const m = req.method;
  let g;
  if (p === "/" && m === "GET") return json({ ok: true, service: "onion-board-store" });
  if (p === "/admin" && m === "GET")
    return new Response(ADMIN_PAGE, { headers: { "content-type": "text/html; charset=utf-8",
      "content-security-policy": "default-src 'self'; style-src 'unsafe-inline'; " +
        "script-src 'unsafe-inline'; media-src 'self' blob:", "cache-control": "no-store" } });
  if (p === "/v1/chat" || /^\/v1\/chat\/\d+\/report$/.test(p)) return chatRoute(req, env);
  if (p === "/v1/sounds" && m === "GET") return list(url, req, env);
  if (p === "/v1/sounds" && m === "POST") return upload(req, env);
  if (p === "/v1/links" && m === "POST") return shareLink(req, env);
  if ((g = p.match(/^\/v1\/sounds\/([0-9a-f]{12})\/file$/)) && m === "GET")
    return file(env, g[1], false);
  if ((g = p.match(/^\/v1\/sounds\/([0-9a-f]{12})\/vote$/)) && m === "POST")
    return vote(req, env, g[1]);
  if ((g = p.match(/^\/v1\/sounds\/([0-9a-f]{12})\/report$/)) && m === "POST")
    return report(req, env, g[1]);
  if (p.startsWith("/v1/admin/")) {
    await admin(req, env);
    if (p === "/v1/admin/chat" || p.startsWith("/v1/admin/chat/")) return chatRoute(req, env);
    if (p === "/v1/admin/queue" && m === "GET") return queue(url, env);
    if (p === "/v1/admin/import" && m === "POST") return upload(req, env, true);
    if ((g = p.match(/^\/v1\/admin\/sounds\/([0-9a-f]{12})\/file$/)) && m === "GET")
      return file(env, g[1], true);
    if ((g = p.match(/^\/v1\/admin\/sounds\/([0-9a-f]{12})$/)) && m === "POST")
      return review(req, env, g[1]);
  }
  return json({ error: "not found" }, 404);
}

// ------------------------------------------------------------------ helpers

async function sha256(data) {
  const buf = typeof data === "string" ? new TextEncoder().encode(data) : data;
  const h = await crypto.subtle.digest("SHA-256", buf);
  return [...new Uint8Array(h)].map(b => b.toString(16).padStart(2, "0")).join("");
}

const now = () => Math.floor(Date.now() / 1000);
const today = () => Math.floor(Date.now() / 86400000);

async function installHash(req, env, required = true) {
  const id = (req.headers.get("x-onion-install") || "").toLowerCase();
  if (!INSTALL_RE.test(id)) {
    if (required) fail("install id");
    return "";
  }
  return sha256(`${env.SALT || ""}:install:${id}`);
}

async function ipHash(req, env) {
  const ip = req.headers.get("cf-connecting-ip") || "local";
  return sha256(`${env.SALT || ""}:ip:${ip}`);
}

// counts one more `what` for `who` today; false (and not counted) once `limit` is reached
async function allow(env, what, who, limit) {
  const key = `${what}:${who}`;
  const day = today();
  const row = await env.DB.prepare("SELECT n FROM counters WHERE key = ? AND day = ?")
    .bind(key, day).first();
  if (row && row.n >= limit) return false;
  await env.DB.prepare("INSERT INTO counters (key, day, n) VALUES (?, ?, 1) " +
    "ON CONFLICT (key, day) DO UPDATE SET n = n + 1").bind(key, day).run();
  return true;
}

function cleanName(s) {
  return String(s || "").replace(/[\u0000-\u001f\u007f]/g, " ").replace(/\s+/g, " ")
    .trim().slice(0, 60);
}

function cleanTags(s) {
  return String(s || "").toLowerCase().split(/[,#]/).map(t => cleanName(t).slice(0, 24))
    .filter(Boolean).slice(0, 8).join(",");
}

// the audio type from the file's first bytes (never from its name), or ""
function sniff(b) {
  const s = (i, n) => String.fromCharCode(...b.slice(i, i + n));
  if (b.length < 12) return "";
  if (s(0, 4) === "fLaC") return "flac";
  if (s(0, 4) === "OggS") return "ogg";
  if (s(0, 4) === "RIFF" && s(8, 4) === "WAVE") return "wav";
  if (s(0, 3) === "ID3" || (b[0] === 0xff && (b[1] & 0xe0) === 0xe0)) return "mp3";
  return "";
}

// one video's link written one way, so the same video can't be shared twice; "" when
// it isn't an https link to one of LINK_SITES
function linkKey(raw) {
  let u;
  try {
    u = new URL(String(raw || "").trim());
  } catch {
    return "";
  }
  if (u.protocol !== "https:" || u.username || u.password || u.port) return "";
  const host = u.hostname.toLowerCase().replace(/^(www|m)\./, "");
  if (!LINK_SITES.some(s => host === s || host.endsWith("." + s))) return "";
  const path = u.pathname.replace(/\/+$/, "");
  if (host === "youtu.be" && path) return "youtube.com/watch?v=" + path.slice(1);
  if (host === "youtube.com" || host === "music.youtube.com") {
    if (path === "/watch" && u.searchParams.get("v"))
      return "youtube.com/watch?v=" + u.searchParams.get("v");
    if (path.startsWith("/shorts/")) return "youtube.com/watch?v=" + path.slice(8);
  }
  return host + path;
}

function shown(r) {
  return { id: r.id, name: r.name, tags: r.tags ? r.tags.split(",") : [], ext: r.ext,
           link: r.link || "",
           size: r.size, author: r.author, up: r.up, down: r.down, created: r.created,
           ...(r.mine !== undefined ? { mine: r.mine || 0 } : {}) };
}

// ------------------------------------------------------------------ public routes

async function list(url, req, env) {
  const sort = url.searchParams.get("sort") === "new" ? "new" : "top";
  const q = cleanName(url.searchParams.get("q")).toLowerCase();
  const offset = Math.max(0, Math.min(10000, parseInt(url.searchParams.get("offset")) || 0));
  const voter = await installHash(req, env, false);
  const where = ["s.status = 'live'"];
  const args = [];
  if (q) {
    for (const word of q.split(" ").slice(0, 5)) {
      where.push("(lower(s.name) LIKE ? ESCAPE '\\' OR s.tags LIKE ? ESCAPE '\\')");
      const like = `%${word.replace(/[\\%_]/g, c => "\\" + c)}%`;
      args.push(like, like);
    }
  }
  const order = sort === "new" ? "s.created DESC"
    : "(s.up - s.down) DESC, s.up DESC, s.created DESC";
  const mine = voter ? ", (SELECT value FROM votes v WHERE v.sound = s.id AND v.voter = ?) AS mine" : "";
  const sql = `SELECT s.*${mine} FROM sounds s WHERE ${where.join(" AND ")} ` +
              `ORDER BY ${order} LIMIT ? OFFSET ?`;
  const rows = await env.DB.prepare(sql)
    .bind(...(voter ? [voter] : []), ...args, PAGE + 1, offset).all();
  const res = rows.results || [];
  return json({ sounds: res.slice(0, PAGE).map(shown), more: res.length > PAGE,
                agreement: AGREEMENT, max_bytes: MAX_BYTES });
}

async function file(env, id, any) {
  const row = await env.DB.prepare("SELECT ext, status FROM sounds WHERE id = ?").bind(id).first();
  if (!row || row.ext === "link" || (!any && row.status !== "live"))
    return json({ error: "not found" }, 404);
  const obj = await env.FILES.get(`${id}.${row.ext}`, "arrayBuffer");
  if (!obj) return json({ error: "not found" }, 404);
  return new Response(obj, { headers: {
    "content-type": TYPES[row.ext] || "application/octet-stream",
    "content-length": String(obj.byteLength),
    "cache-control": any ? "no-store" : "public, max-age=86400",
    "x-content-type-options": "nosniff" } });
}

async function upload(req, env, imported = false) {
  const len = parseInt(req.headers.get("content-length") || "0");
  if (len > MAX_BYTES + 64 * 1024) fail("too big", 413);
  let form;
  try {
    form = await req.formData();
  } catch {
    fail("form");
  }
  const f = form.get("file");
  if (!f || typeof f === "string") fail("file");
  const name = cleanName(form.get("name"));
  if (!name) fail("name");
  if (!imported && form.get("agree") !== AGREEMENT) fail("agreement");
  const bytes = new Uint8Array(await f.arrayBuffer());
  if (!bytes.length || bytes.length > MAX_BYTES) fail("too big", 413);
  const ext = sniff(bytes);
  if (!ext) fail("not audio", 415);
  const uploader = imported ? "owner" : await installHash(req, env);
  const ip = imported ? "owner" : await ipHash(req, env);
  const hash = await sha256(bytes);
  if (await env.DB.prepare("SELECT 1 FROM sounds WHERE sha256 = ?").bind(hash).first())
    fail("duplicate", 409);
  if (!imported) {
    const pending = await env.DB.prepare(
      "SELECT count(*) AS n FROM sounds WHERE status = 'pending'").first();
    if (pending.n >= PENDING_CAP) fail("queue full", 503);
    if (!await allow(env, "upload", uploader, UPLOADS_PER_DAY)
        || !await allow(env, "upload-ip", ip, UPLOADS_PER_IP_DAY)) fail("slow down", 429);
  }
  const id = (await sha256(crypto.randomUUID())).slice(0, 12);
  await env.FILES.put(`${id}.${ext}`, bytes);
  await env.DB.prepare("INSERT INTO sounds (id, name, tags, ext, size, sha256, author, " +
    "uploader, ip, status, created) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")
    .bind(id, name, cleanTags(form.get("tags")), ext, bytes.length, hash,
          imported ? cleanName(form.get("author")) || "Onion Board" : "",
          uploader, ip, imported ? "live" : "pending", now()).run();
  return json({ id, status: imported ? "live" : "pending" }, 201);
}

// share a link: only the link is kept (the app that adds it downloads it from the site)
async function shareLink(req, env) {
  const { link, name, tags, agree } = await body(req);
  if (agree !== LINK_AGREEMENT) fail("agreement");
  const n = cleanName(name);
  if (!n) fail("name");
  const key = linkKey(link);
  if (!key || String(link).length > 500) fail("bad link", 415);
  const hash = await sha256("link:" + key);
  if (await env.DB.prepare("SELECT 1 FROM sounds WHERE sha256 = ?").bind(hash).first())
    fail("duplicate", 409);
  const pending = await env.DB.prepare(
    "SELECT count(*) AS n FROM sounds WHERE status = 'pending'").first();
  if (pending.n >= PENDING_CAP) fail("queue full", 503);
  const uploader = await installHash(req, env);
  const ip = await ipHash(req, env);
  if (!await allow(env, "upload", uploader, UPLOADS_PER_DAY)
      || !await allow(env, "upload-ip", ip, UPLOADS_PER_IP_DAY)) fail("slow down", 429);
  const id = (await sha256(crypto.randomUUID())).slice(0, 12);
  await env.DB.prepare("INSERT INTO sounds (id, name, tags, ext, link, size, sha256, author, " +
    "uploader, ip, status, created) VALUES (?, ?, ?, 'link', ?, 0, ?, '', ?, ?, 'pending', ?)")
    .bind(id, n, cleanTags(tags), "https://" + key, hash, uploader, ip, now()).run();
  return json({ id, status: "pending" }, 201);
}

async function body(req) {
  try {
    return await req.json();
  } catch {
    fail("json");
  }
}

async function counts(env, id) {
  await env.DB.prepare("UPDATE sounds SET " +
    "up = (SELECT count(*) FROM votes WHERE sound = ?1 AND value = 1), " +
    "down = (SELECT count(*) FROM votes WHERE sound = ?1 AND value = -1) WHERE id = ?1")
    .bind(id).run();
  return env.DB.prepare("SELECT up, down FROM sounds WHERE id = ?").bind(id).first();
}

async function vote(req, env, id) {
  const voter = await installHash(req, env);
  const { value } = await body(req);
  if (![1, -1, 0].includes(value)) fail("value");
  const row = await env.DB.prepare("SELECT status FROM sounds WHERE id = ?").bind(id).first();
  if (!row || row.status !== "live") fail("not found", 404);
  if (!await allow(env, "vote-ip", await ipHash(req, env), VOTES_PER_IP_DAY)) fail("slow down", 429);
  if (value === 0) {
    await env.DB.prepare("DELETE FROM votes WHERE sound = ? AND voter = ?").bind(id, voter).run();
  } else {
    await env.DB.prepare("INSERT INTO votes (sound, voter, value) VALUES (?, ?, ?) " +
      "ON CONFLICT (sound, voter) DO UPDATE SET value = excluded.value")
      .bind(id, voter, value).run();
  }
  const c = await counts(env, id);
  return json({ id, up: c.up, down: c.down, mine: value });
}

async function report(req, env, id) {
  const voter = await installHash(req, env);
  const { reason } = await body(req);
  const why = ["copyright", "offensive", "broken", "other"].includes(reason) ? reason : "other";
  const row = await env.DB.prepare("SELECT status FROM sounds WHERE id = ?").bind(id).first();
  if (!row || row.status !== "live") fail("not found", 404);
  if (!await allow(env, "vote-ip", await ipHash(req, env), VOTES_PER_IP_DAY)) fail("slow down", 429);
  await env.DB.prepare("INSERT OR IGNORE INTO reports (sound, voter, reason, created) " +
    "VALUES (?, ?, ?, ?)").bind(id, voter, why, now()).run();
  const n = (await env.DB.prepare("SELECT count(*) AS n FROM reports WHERE sound = ?")
    .bind(id).first()).n;
  // enough reports: off the store until the owner looks at it again
  await env.DB.prepare("UPDATE sounds SET reports = ?, " +
    "status = CASE WHEN ? >= ? THEN 'pending' ELSE status END WHERE id = ?")
    .bind(n, n, REPORTS_TO_HIDE, id).run();
  return json({ id, reported: true });
}

// ------------------------------------------------------------------ the owner's routes

async function admin(req, env) {
  const got = (req.headers.get("authorization") || "").replace(/^Bearer\s+/i, "");
  const want = env.ADMIN_TOKEN || "";
  if (!want || got.length !== want.length) fail("unauthorized", 401);
  // compare the hashes, so the time taken says nothing about the token
  const [a, b] = await Promise.all([sha256(got), sha256(want)]);
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  if (diff) fail("unauthorized", 401);
}

async function queue(url, env) {
  const status = ["pending", "live", "rejected"].includes(url.searchParams.get("status"))
    ? url.searchParams.get("status") : "pending";
  const rows = await env.DB.prepare(
    "SELECT s.*, (SELECT group_concat(reason) FROM reports r WHERE r.sound = s.id) AS why " +
    "FROM sounds s WHERE status = ? ORDER BY reports DESC, created ASC LIMIT 200")
    .bind(status).all();
  return json({ sounds: (rows.results || []).map(r => ({ ...shown(r), status: r.status,
    reports: r.reports, why: r.why || "" })) });
}

async function review(req, env, id) {
  const { action, name } = await body(req);
  const row = await env.DB.prepare("SELECT ext, status FROM sounds WHERE id = ?").bind(id).first();
  if (!row) fail("not found", 404);
  if (action === "approve") {
    // a rejected upload's file is deleted: it can't go live again (a link has no file)
    if (row.status === "rejected" && row.ext !== "link") fail("file gone", 409);
    // approved again after reports: the old reports are dealt with
    await env.DB.prepare("DELETE FROM reports WHERE sound = ?").bind(id).run();
    await env.DB.prepare("UPDATE sounds SET status = 'live', reports = 0, reviewed = ? WHERE id = ?")
      .bind(now(), id).run();
  } else if (action === "reject") {
    // the file goes at once; the row stays so the same file can't come back
    if (row.ext !== "link") await env.FILES.delete(`${id}.${row.ext}`);
    await env.DB.prepare("UPDATE sounds SET status = 'rejected', reviewed = ? WHERE id = ?")
      .bind(now(), id).run();
  } else if (action === "rename") {
    const n = cleanName(name);
    if (!n) fail("name");
    await env.DB.prepare("UPDATE sounds SET name = ? WHERE id = ?").bind(n, id).run();
  } else {
    fail("action");
  }
  return json({ id, done: action });
}
