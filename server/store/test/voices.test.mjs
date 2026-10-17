// Community voices (src/voices.js). Run: node --test test/
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import worker from "../src/index.js";
import { plain, rebuild } from "../src/voices.js";

const SCHEMA = readFileSync(new URL("../schema.sql", import.meta.url), "utf8");
const TOKEN = "t".repeat(40);
const INSTALL = "0123456789abcdef0123";

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
  rows(sql, ...a) { return this.db.prepare(sql).all(...a); }
}

const store = (extra = {}) => ({ DB: new FakeD1(), FILES: null, SALT: "salt", ADMIN_TOKEN: TOKEN,
                                 ...extra });

async function call(env, path, { method = "GET", json, raw, ip = "1.1.1.1", install = INSTALL,
                                 admin = false } = {}) {
  const h = { "cf-connecting-ip": ip };
  if (install) h["x-onion-install"] = install;
  if (admin) h.authorization = `Bearer ${TOKEN}`;
  let body = raw;
  if (json !== undefined) { body = JSON.stringify(json); h["content-type"] = "application/json"; }
  const res = await worker.fetch(new Request("https://store.test" + path, { method, headers: h, body }), env);
  return { status: res.status, body: await res.json() };
}

const VOICE = { kind: "fx", name: "Squeaky robot", about: "Beep boop", emoji: "🤖",
                tags: "robot, #Funny", data: { e: { robot: { mix: 0.8 }, pitch: { semitones: 7 } } } };
const share = (env, v = VOICE, opts = {}) => call(env, "/v1/voices", { method: "POST", json: v, ...opts });

test("a shared voice is live at once, rebuilt from its checked fields only", async () => {
  const env = store();
  const up = await share(env, { ...VOICE, extra: "x",
                                data: { e: { robot: { mix: 0.8, evil: 1 } }, script: "rm -rf /" } });
  assert.equal(up.status, 201);
  assert.equal(up.body.status, "live");
  const got = await call(env, "/v1/voices");
  assert.equal(got.body.voices.length, 1);
  const v = got.body.voices[0];
  assert.deepEqual(v.data, { e: { robot: { mix: 0.8, evil: 1 } } });   // no "script"
  assert.deepEqual([v.kind, v.name, v.emoji, v.tags], ["fx", "Squeaky robot", "🤖", ["robot", "funny"]]);
  assert.deepEqual(env.DB.rows("SELECT kind FROM actions").map(r => r.kind), ["voice"]);
  // the same settings again under another name: a duplicate, with the first one's id
  const again = await share(env, { ...VOICE, name: "Copy", data: { e: { robot: { evil: 1, mix: 0.8 } } } });
  assert.deepEqual([again.status, again.body.id], [409, up.body.id]);
});

test("names and texts that could break a screen come out as one plain line", async () => {
  const env = store();
  const nasty = "\u202Eevil\u200B\u0000name\n\r\t<b>bold</b> Z" + "\u0301".repeat(60) + " ﷽".repeat(40);
  const up = await share(env, { ...VOICE, name: nasty, about: "a\u2028b\u2066c" + "x".repeat(500),
                                emoji: "👨‍👩‍👧" });
  assert.equal(up.status, 201);
  const v = (await call(env, "/v1/voices")).body.voices[0];
  assert.ok(!/[\u0000-\u001f\u007f\u200b\u202e\u2066\u2028]/.test(v.name + v.about));
  assert.ok([...v.name].length <= 32 && [...v.about].length <= 140);
  assert.ok(!/\p{M}{3}/u.test(v.name));                  // no "zalgo" pile-up
  assert.ok(v.name.includes("b bold /b") && !/[<>`{}\\]/.test(v.name + v.about));   // as sound names
  assert.equal(v.emoji, "");                              // a joined sequence isn't one emoji
  assert.equal((await share(env, { ...VOICE, name: "\u200B\u202E \n" })).status, 400);
  assert.equal(plain("a\uD800b", 10), "a b");             // a lone surrogate goes
  assert.equal(plain("🐿️🐿️🐿️", 2), "🐿️");                    // cut between characters, not inside
});

test("blocked words and links in a voice's name or about are refused", async () => {
  const env = store({ CHAT_BLOCK: "badword" });
  assert.equal((await share(env, { ...VOICE, name: "my B.A.D word voice" })).status, 422);
  assert.equal((await share(env, { ...VOICE, about: "so badword" })).status, 422);
  assert.equal((await share(env, { ...VOICE, about: "visit https://x.com" })).status, 422);
  assert.equal((await share(env)).status, 201);
});

test("settings that can't be a voice are refused; numbers out of range are pulled in", async () => {
  const env = store();
  const bad = [
    { kind: "fx", data: { e: {} } },
    { kind: "fx", data: { e: { robot: { mix: "1" } } } },
    { kind: "fx", data: { e: { robot: { mix: true } } } },
    { kind: "fx", data: { e: { robot: { mix: null } } } },
    { kind: "fx", data: { e: { "Robot!": { mix: 1 } } } },
    { kind: "fx", data: { e: { robot: { "x-y": 1 } } } },
    { kind: "fx", data: { e: Object.fromEntries([...Array(40)].map((_, i) => [`e${i}`, {}])) } },
    { kind: "fx", data: { e: { robot: [1, 2] } } },
    { kind: "fx", data: [] },
    { kind: "fx" },
    { kind: "ai", data: { mix: [], pitch_hz: 100 } },
    { kind: "ai", data: { mix: [[1.5, 1]], pitch_hz: 100 } },
    { kind: "ai", data: { mix: [[1, 0]], pitch_hz: 100 } },
    { kind: "ai", data: { mix: [[1, 1], [2, 1], [3, 1], [4, 1], [5, 1]], pitch_hz: 100 } },
    { kind: "ai", data: { mix: [[1, 1]] } },
    { kind: "setup", data: {} },
    { kind: "setup", data: { lang: "../../etc" } },
    { kind: "setup", data: { ai: { id: "C:\\evil" } } },
    { kind: "setup", data: { ai: { id: "bear", mix: "x" } } },
    { kind: "nope", data: { e: { robot: { mix: 1 } } } },
  ];
  for (const b of bad) {
    const r = await share(env, { name: "x", ...b });
    assert.ok([400, 422].includes(r.status), JSON.stringify(b) + " -> " + r.status);
  }
  assert.equal(env.DB.rows("SELECT * FROM voices").length, 0);
  const ai = await share(env, { kind: "ai", name: "Low", data: { mix: [[171, 9]], formant: -50, pitch_hz: 1e9 } });
  assert.equal(ai.status, 201);
  assert.deepEqual((await call(env, "/v1/voices?kind=ai")).body.voices[0].data,
                   { mix: [[171, 1]], formant: -2, pitch_hz: 400 });
  // a setup keeps only its known parts; someone's own AI voice travels with its blend
  assert.deepEqual(rebuild("setup", {
    e: { robot: { mix: 1 } }, fx: "Robot\u202E", lang: "pt-BR", junk: 1,
    ai: { id: "my-1234abcd", name: "Mine", pitch: 99, mix: [[5, 1]], formant: 0, pitch_hz: 150, x: 1 } }),
    { e: { robot: { mix: 1 } }, fx: "Robot", lang: "pt-BR",
      ai: { id: "my-1234abcd", name: "Mine", pitch: 12, mix: [[5, 1]], formant: 0, pitch_hz: 150 } });
});

test("junk thrown at the voice routes never gets a bad voice in or a 500 out", async () => {
  const env = store();
  let seed = 7;
  const rnd = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
  const atoms = [null, true, 0, -1, 1e308, -1e308, 0.5, 3, "", "x", "\u202E", [], {}, [[1, 1]], "🤖",
                 { mix: 1 }, "__proto__", "constructor", "robot", "e", "mix", "a".repeat(5000)];
  const pick = () => atoms[Math.floor(rnd() * atoms.length)];
  const junk = d => {
    if (d > 3 || rnd() < 0.3) return pick();
    if (rnd() < 0.4) return [...Array(Math.floor(rnd() * 4))].map(() => junk(d + 1));
    return Object.fromEntries([...Array(Math.floor(rnd() * 4))].map(() =>
      [String(pick()).slice(0, 30), junk(d + 1)]));
  };
  for (let i = 0; i < 1500; i++) {
    const v = { kind: ["fx", "ai", "setup"][i % 3], name: junk(2), about: junk(2), emoji: junk(3),
                tags: junk(3), data: junk(0) };
    const r = await share(env, v, { install: (1e15 + i).toString(16).padStart(16, "0"),
                                    ip: `9.${i % 250}.${i % 7}.1` });
    assert.ok(r.status < 500, `${r.status} ${JSON.stringify(v).slice(0, 300)}`);
  }
  for (const r of env.DB.rows("SELECT * FROM voices")) {
    assert.ok(r.name && [...r.name].length <= 32 && !/[\p{Cc}\p{Cf}]/u.test(r.name), r.name);
    assert.deepEqual(rebuild(r.kind, JSON.parse(r.data)), JSON.parse(r.data));   // already clean
  }
  for (const raw of ["{", "[]", "null", "1", "x".repeat(20000)]) {
    const res = await call(env, "/v1/voices", { method: "POST", raw });
    assert.ok([400, 413].includes(res.status), raw.slice(0, 20) + " " + res.status);
  }
});

test("votes, filters, search; reports from 3 addresses hide a voice until the owner looks", async () => {
  const env = store();
  const a = (await share(env)).body.id;
  const b = (await share(env, { kind: "ai", name: "Deep guy", tags: "deep",
                                data: { mix: [[171, 1]], pitch_hz: 90 } })).body.id;
  const up = await call(env, `/v1/voices/${b}/vote`, { method: "POST", json: { value: 1 } });
  assert.deepEqual([up.status, up.body.up], [200, 1]);
  let list = (await call(env, "/v1/voices")).body.voices;
  assert.deepEqual(list.map(v => v.id), [b, a]);           // top first
  assert.equal(list[0].mine, 1);
  assert.deepEqual((await call(env, "/v1/voices?kind=fx")).body.voices.map(v => v.id), [a]);
  assert.deepEqual((await call(env, "/v1/voices?q=deep")).body.voices.map(v => v.id), [b]);
  for (const ip of ["1.0.0.1", "1.0.0.2", "1.0.0.3"])
    await call(env, `/v1/voices/${a}/report`, { method: "POST", json: { reason: "offensive" }, ip });
  assert.deepEqual((await call(env, "/v1/voices")).body.voices.map(v => v.id), [b]);
  assert.equal((await call(env, `/v1/voices/${a}/vote`, { method: "POST", json: { value: 1 } })).status, 404);
  const hidden = await call(env, "/v1/admin/voices", { admin: true });
  assert.deepEqual(hidden.body.voices.map(v => [v.id, v.reports]), [[a, 3]]);
  assert.equal((await call(env, "/v1/admin/voices")).status, 401);
  const back = await call(env, `/v1/admin/voices/${a}`, { method: "POST", admin: true, json: { action: "live" } });
  assert.equal(back.status, 200);
  assert.equal((await call(env, "/v1/voices")).body.voices.length, 2);
  // a sound's routes don't reach a voice
  assert.equal((await call(env, `/v1/sounds/${a}/vote`, { method: "POST", json: { value: 1 } })).status, 404);
});

test("20 voices a day per install", async () => {
  const env = store();
  for (let i = 0; i < 20; i++)
    assert.equal((await share(env, { ...VOICE, data: { e: { robot: { mix: i / 100 } } } })).status, 201);
  assert.equal((await share(env, { ...VOICE, data: { e: { robot: { mix: 0.99 } } } })).status, 429);
});
