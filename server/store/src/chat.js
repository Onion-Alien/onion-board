// The Chat tab's server: one anonymous, text-only room, kept in a Cloudflare Durable Object.
//
// Nobody picks a name and nothing is stored on disk. Each time the app is opened it makes
// a random session id and the server turns it, with the install's hash, into a silly
// two-word name ("Cute Onion", "Red Car", "Explicit Waterfall"), so a name lasts only
// until the app is closed and can't be used to follow anyone. The room remembers only the last MAX_KEPT messages, in
// memory. The app asks for new messages with a long poll (it holds the request open
// until something arrives or POLL_MS passes), which keeps Offline mode, the proxy and
// Tor working the same as every other feature.
//
// Safety, because anyone can say anything: text only (no links, no pictures), a short
// message, a rate limit per install and per address, repeats refused, reports (3
// different people mute that person for an hour), a ban list the owner controls from
// /v1/admin/chat/..., and a kill switch (CHAT_OFF=1, or POST /v1/admin/chat/off).

const MAX_LEN = 280;
const MAX_KEPT = 60;
const POLL_MS = 20000;
const PER_INSTALL = [1500, 20];      // at most 20 messages a minute, 1.5 s apart
const PER_IP_MINUTE = 60;
const REPORTS_TO_MUTE = 3;
const MUTE_MS = 3600 * 1000;
const MAX_REPORTS = 200;
const INSTALL_RE = /^[0-9a-f-]{16,64}$/;
const SESSION_RE = /^[0-9a-f]{16,32}$/;

const ADJ = ["Cute", "Red", "Explicit", "Sleepy", "Soggy", "Crunchy", "Spicy", "Dizzy",
  "Fuzzy", "Grumpy", "Sneaky", "Wobbly", "Cursed", "Moist", "Feral", "Salty", "Lumpy",
  "Shiny", "Bored", "Haunted", "Chonky", "Mighty", "Suspicious", "Tiny", "Legendary",
  "Confused", "Hungry", "Naughty", "Unhinged", "Sweaty", "Smug", "Angry", "Blue", "Green",
  "Golden", "Greasy", "Damp", "Fancy", "Rogue", "Sticky", "Lazy", "Radical", "Cozy",
  "Rowdy", "Awkward", "Majestic", "Unholy", "Slippery", "Jolly", "Wet", "Big", "Evil"];
const NOUN = ["Onion", "Car", "Waterfall", "Goblin", "Pickle", "Toaster", "Walrus", "Noodle",
  "Banana", "Raccoon", "Wizard", "Potato", "Pigeon", "Muffin", "Gremlin", "Turnip", "Llama",
  "Cactus", "Badger", "Waffle", "Penguin", "Moth", "Biscuit", "Otter", "Newt", "Kettle",
  "Sandwich", "Volcano", "Couch", "Sock", "Meatball", "Dumpster", "Bagel", "Pancake",
  "Tractor", "Hamster", "Cabbage", "Trombone", "Lasagna", "Mushroom", "Fridge", "Ferret",
  "Submarine", "Cheese", "Crab", "Lobster", "Bus", "Duck", "Ghost", "Sausage", "Parrot",
  "Pizza", "Cloud", "Spoon", "Tomato", "Yeti"];

// links of any kind (so no spam, no invites, no pictures): schemes, www., and name.tld/
const LINK = /(https?:|ftp:|www\.|\b[a-z0-9-]{2,}\.(com|net|org|io|gg|ly|me|co|tv|xyz|app|dev|ru|to|cc)\b|discord\.gg|[a-z0-9-]+\.[a-z]{2,}\/)/i;

export async function sha256(s) {
  const h = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return [...new Uint8Array(h)].map(b => b.toString(16).padStart(2, "0")).join("");
}

export function clean(text) {
  return String(text || "").normalize("NFKC")
    .replace(/[\u0000-\u001f\u007f-\u009f​-‏‪-‮⁦-⁩﻿]/g, " ")
    .replace(/\s+/g, " ").trim();
}

// the two-word name a hash gives ("Cute Onion"); `skip` > 0 gives the next one along
export function nameFor(hash, skip = 0) {
  const n = (parseInt(hash.slice(0, 8), 16) + skip * 7919) % (ADJ.length * NOUN.length);
  return `${ADJ[n % ADJ.length]} ${NOUN[Math.floor(n / ADJ.length) % NOUN.length]}`;
}

// why `text` can't be said, or "" when it can
export function refuse(text, blocked = []) {
  if (!text) return "empty";
  if (text.length > MAX_LEN) return "too long";
  if (LINK.test(text)) return "no links";
  const low = text.toLowerCase().replace(/[^a-z0-9]+/g, "");
  for (const w of blocked) if (w && low.includes(w)) return "not allowed";
  return "";
}

function json(body, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: {
    "content-type": "application/json; charset=utf-8", "cache-control": "no-store" } });
}

// The room's state and rules, with no Cloudflare in it, so it can be tested in Node.
export class Room {
  constructor(blocked = []) {
    this.msgs = [];            // newest last: {id, t, u, name, text}
    this.seq = 0;
    this.last = new Map();     // who -> [time of last message, recent times, last text]
    this.ips = new Map();      // ip hash -> [window start, count]
    this.names = new Map();    // session tag -> its name (kept so nobody shares a name)
    this.muted = new Map();    // who -> until (ms)
    this.banned = new Set();   // who hashes
    this.reports = [];         // {id, t, who, name, text, by: [reporters]}
    this.blocked = blocked.map(w => w.toLowerCase().replace(/[^a-z0-9]+/g, "")).filter(Boolean);
    this.off = false;
    this.waiters = [];
  }

  since(after) {
    return this.msgs.filter(m => m.id > after).map(({ id, t, u, name, text }) =>
      ({ id, t, u, name, text }));
  }

  // who = install hash, ipk = address hash; returns {ok, ...} or {error}
  say(who, ipk, rawText, now = Date.now()) {
    if (this.off) return { error: "off", status: 503 };
    if (this.banned.has(who)) return { error: "banned", status: 403 };
    if ((this.muted.get(who) || 0) > now) return { error: "muted", status: 403 };
    const text = clean(rawText);
    const why = refuse(text, this.blocked);
    if (why) return { error: why, status: 400 };
    const rec = this.last.get(who) || [0, [], ""];
    if (now - rec[0] < PER_INSTALL[0]) return { error: "slow down", status: 429 };
    rec[1] = rec[1].filter(t => now - t < 60000);
    if (rec[1].length >= PER_INSTALL[1]) return { error: "slow down", status: 429 };
    if (rec[2] === text.toLowerCase() && now - rec[0] < 30000)
      return { error: "repeat", status: 400 };
    let ip = this.ips.get(ipk);
    if (!ip || now - ip[0] > 60000) ip = [now, 0];
    if (ip[1] >= PER_IP_MINUTE) return { error: "slow down", status: 429 };
    ip[1]++;
    this.ips.set(ipk, ip);
    rec[0] = now; rec[1].push(now); rec[2] = text.toLowerCase();
    this.last.set(who, rec);
    const msg = { id: ++this.seq, t: now, u: "", name: "", text, who };
    return { ok: true, msg };
  }

  // the name for session tag `u`: the same one every time, never one someone else has now
  nameOf(u, hash) {
    const had = this.names.get(u);
    if (had) return had;
    const used = new Set(this.names.values());
    let name = nameFor(hash), k = 0;
    while (used.has(name) && k < 40) name = nameFor(hash, ++k);
    this.names.set(u, name);
    if (this.names.size > 400) this.names.delete(this.names.keys().next().value);
    return name;
  }

  push(msg, u, name) {
    const { who, ...shown } = msg;
    shown.u = u; shown.name = name;
    this.msgs.push({ ...shown, who });
    if (this.msgs.length > MAX_KEPT) this.msgs.splice(0, this.msgs.length - MAX_KEPT);
    const w = this.waiters; this.waiters = [];
    for (const f of w) f();
    return shown;
  }

  report(id, reporter, now = Date.now()) {
    const m = this.msgs.find(x => x.id === id);
    if (!m) return { error: "gone", status: 404 };
    let r = this.reports.find(x => x.id === id);
    if (!r) {
      r = { id, t: now, who: m.who, name: m.name, text: m.text, by: [] };
      this.reports.push(r);
      if (this.reports.length > MAX_REPORTS) this.reports.shift();
    }
    if (!r.by.includes(reporter)) r.by.push(reporter);
    if (r.by.length >= REPORTS_TO_MUTE) {
      this.muted.set(m.who, now + MUTE_MS);
      // what they said comes off the screen for everyone
      this.msgs = this.msgs.filter(x => x.who !== m.who);
    }
    return { ok: true };
  }

  wait(after, ms = POLL_MS) {
    if (this.seq !== after) return Promise.resolve();   // lower = the room started over
    return new Promise(res => {
      const t = setTimeout(res, ms);
      this.waiters.push(() => { clearTimeout(t); res(); });
    });
  }
}

// The Durable Object: one room for everyone. index.js sends /v1/chat... here.
export class ChatRoom {
  constructor(state, env) {
    this.state = state;
    this.env = env;
    this.room = new Room(String(env.CHAT_BLOCK || "").split(","));
    this.room.off = String(env.CHAT_OFF || "") === "1";
    this.ready = state.blockConcurrencyWhile(async () => {
      const kept = await state.storage.get(["banned", "off"]);
      if (kept.get("banned")) this.room.banned = new Set(kept.get("banned"));
      if (kept.get("off") !== undefined) this.room.off = !!kept.get("off");
    });
  }

  async fetch(req) {
    await this.ready;
    const room = this.room;
    const url = new URL(req.url);
    const who = req.headers.get("x-chat-who") || "";
    const ipk = req.headers.get("x-chat-ip") || "";
    const user = req.headers.get("x-chat-user") || "";
    const p = url.pathname;
    let g;
    if (p === "/v1/chat" && req.method === "GET") {
      if (room.off) return json({ error: "off" }, 503);
      const after = Math.max(0, parseInt(url.searchParams.get("after") || "0", 10) || 0);
      // a number lower than the room's means the room started over: send everything
      if (url.searchParams.get("wait") === "1") await room.wait(after);
      const all = after > room.seq ? 0 : after;
      return json({ messages: room.since(all), last: room.seq, off: room.off });
    }
    if (p === "/v1/chat" && req.method === "POST") {
      let body;
      try { body = await req.json(); } catch { return json({ error: "bad request" }, 400); }
      const r = room.say(who, ipk, body && body.text);
      if (r.error) return json({ error: r.error }, r.status);
      const u = user.slice(0, 8);
      const shown = room.push(r.msg, u, room.nameOf(u, user));
      return json({ message: shown, last: room.seq });
    }
    if ((g = p.match(/^\/v1\/chat\/(\d+)\/report$/)) && req.method === "POST") {
      const r = room.report(parseInt(g[1], 10), who);
      return r.error ? json({ error: r.error }, r.status) : json({ ok: true });
    }
    if (p === "/v1/admin/chat" && req.method === "GET") {
      return json({ off: room.off, banned: room.banned.size,
        reports: room.reports.map(({ id, t, name, text, by, who: w }) =>
          ({ id, t, name, text, reports: by.length, who: w })) });
    }
    if (p === "/v1/admin/chat/off" && req.method === "POST") {
      const b = await req.json().catch(() => ({}));
      room.off = !!b.off;
      await this.state.storage.put("off", room.off);
      for (const f of room.waiters.splice(0)) f();
      return json({ off: room.off });
    }
    if (p === "/v1/admin/chat/ban" && req.method === "POST") {
      const b = await req.json().catch(() => ({}));
      const w = String(b.who || "");
      if (!/^[0-9a-f]{64}$/.test(w)) return json({ error: "who" }, 400);
      if (b.ban === false) room.banned.delete(w); else room.banned.add(w);
      room.msgs = room.msgs.filter(m => m.who !== w);
      await this.state.storage.put("banned", [...room.banned]);
      return json({ banned: room.banned.size });
    }
    return json({ error: "not found" }, 404);
  }
}

// index.js calls this for /v1/chat... and /v1/admin/chat... (after checking the admin
// token for the second): it names the caller by hashes and hands over to the room.
export async function chatRoute(req, env) {
  const id = (req.headers.get("x-onion-install") || "").toLowerCase();
  const p = new URL(req.url).pathname;
  const session = (req.headers.get("x-onion-session") || "").toLowerCase();
  if (!p.startsWith("/v1/admin/") && !(INSTALL_RE.test(id) && SESSION_RE.test(session)))
    return json({ error: "install id" }, 400);
  const ip = req.headers.get("cf-connecting-ip") || "local";
  const headers = new Headers(req.headers);
  headers.set("x-chat-who", await sha256(`${env.SALT || ""}:chat:${id}`));
  headers.set("x-chat-user", await sha256(`${env.SALT || ""}:chatname:${id}:${session}`));
  headers.set("x-chat-ip", await sha256(`${env.SALT || ""}:ip:${ip}`));
  const stub = env.CHAT.get(env.CHAT.idFromName("room"));
  return stub.fetch(new Request(req, { headers }));
}
