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
// different people, from different addresses, mute that person and their address for an
// hour), a ban list the owner controls from /v1/admin/chat/... (an install and the
// addresses it spoke from), and a kill switch (CHAT_OFF=1, or POST /v1/admin/chat/off).
// A new install id is free to make, so anything that counts people counts addresses too.

const MAX_LEN = 280;
const MAX_KEPT = 60;
const POLL_MS = 20000;
const PER_INSTALL = [1500, 20];      // at most 20 messages a minute, 1.5 s apart
const PER_IP_MINUTE = 60;
const REPORTS_TO_MUTE = 3;
const MUTE_MS = 3600 * 1000;
const MAX_REPORTS = 200;
const REPORTS_PER_IP = [600000, 10]; // at most 10 reports in 10 minutes from one address
const PRUNE_MS = 10000;              // how often the rate-limit records are tidied
const QUICK_MS = 2000;               // a poll this soon after the last answer waits for news
const QUICK_HOLD_MS = 10000;         // ...this long at most when it didn't ask to wait (2.3.0
                                     // gives up on those after 15 s)
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
const LINK = /(https?:|ftp:|file:|data:|javascript:|www\.|\b[a-z0-9-]{2,}\.(com|net|org|io|gg|ly|me|co|tv|xyz|app|dev|ru|to|cc|info|biz|site|online|shop|top|link|click|su|pw|cn|uk)\b|discord\.gg|[a-z0-9-]+\.[a-z]{2,}\/)/i;

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

// text as bare letters, so a blocked word can't hide behind accents, spaces, dots or
// look-alike digits and signs ("Ş.h-1 t" -> "shit")
const LEET = { "@": "a", "$": "s", "!": "i", "|": "i", "0": "o", "1": "i", "3": "e",
               "4": "a", "5": "s", "7": "t", "8": "b", "9": "g" };
export function squash(text) {
  return String(text || "").normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase()
    .replace(/[@$!|013457890]/g, c => LEET[c] || c).replace(/[^a-z]+/g, "");
}

// a blocked word as a pattern on squashed text: each letter may be stretched ("fuuuck")
const WORD_RE = new Map();
function wordRe(w) {
  let re = WORD_RE.get(w);
  if (!re) {
    re = new RegExp([...squash(w)].map(c => c + "+").join(""));
    WORD_RE.set(w, re);
  }
  return re;
}

// whether `text` holds one of the `blocked` words (the owner's CHAT_BLOCK list)
export function hasBlocked(text, blocked = []) {
  const low = squash(text);
  return blocked.some(w => squash(w) && wordRe(w).test(low));
}

// why `text` can't be said, or "" when it can
export function refuse(text, blocked = []) {
  if (!text) return "empty";
  if (text.length > MAX_LEN) return "too long";
  if (LINK.test(text)) return "no links";
  if (hasBlocked(text, blocked)) return "not allowed";
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
    this.reporting = new Map(); // ip hash -> times of its recent reports
    this.polled = new Map();   // who -> when their last poll was answered
    this.names = new Map();    // session tag -> its name (kept so nobody shares a name)
    this.muted = new Map();    // who or ip hash -> until (ms)
    this.banned = new Set();   // who and ip hashes
    this.linked = new Map();   // a banned who -> the ip hashes banned with it (for unbanning)
    this.reports = [];         // {id, t, who, ip, name, text, by: [reporters], byIp: [their ips]}
    this.pruned = 0;
    this.blocked = blocked.map(squash).filter(Boolean);
    this.off = false;
    this.waiters = [];
  }

  since(after) {
    return this.msgs.filter(m => m.id > after).map(({ id, t, u, name, text }) =>
      ({ id, t, u, name, text }));
  }

  // drop rate-limit records nobody needs any more, so new install ids can't fill the memory
  prune(now) {
    if (now - this.pruned < PRUNE_MS) return;
    this.pruned = now;
    for (const [k, rec] of this.last) if (now - rec[0] > 60000) this.last.delete(k);
    for (const [k, ip] of this.ips) if (now - ip[0] > 60000) this.ips.delete(k);
    for (const [k, until] of this.muted) if (until <= now) this.muted.delete(k);
    for (const [k, t] of this.polled) if (now - t > 60000) this.polled.delete(k);
    for (const [k, ts] of this.reporting) {
      const keep = ts.filter(t => now - t < REPORTS_PER_IP[0]);
      if (keep.length) this.reporting.set(k, keep); else this.reporting.delete(k);
    }
  }

  // ban an install and every address it said something from that the room still knows of
  // (or one address on its own); `ban` false lifts it again
  ban(hash, ban = true) {
    const all = new Set([hash, ...(this.linked.get(hash) || [])]);
    if (!ban) {
      for (const h of all) this.banned.delete(h);
      this.linked.delete(hash);
      return all.size;
    }
    for (const m of [...this.msgs, ...this.reports]) if (m.who === hash && m.ip) all.add(m.ip);
    for (const h of all) this.banned.add(h);
    if (all.size > 1) this.linked.set(hash, [...all].filter(h => h !== hash));
    this.msgs = this.msgs.filter(m => !all.has(m.who) && !all.has(m.ip));
    return all.size;
  }

  // who = install hash, ipk = address hash; returns {ok, ...} or {error}
  say(who, ipk, rawText, now = Date.now()) {
    if (this.off) return { error: "off", status: 503 };
    this.prune(now);
    if (this.banned.has(who) || this.banned.has(ipk)) return { error: "banned", status: 403 };
    if (Math.max(this.muted.get(who) || 0, this.muted.get(ipk) || 0) > now)
      return { error: "muted", status: 403 };
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
    const msg = { id: ++this.seq, t: now, u: "", name: "", text, who, ip: ipk };
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
    const { who, ip, ...shown } = msg;
    shown.u = u; shown.name = name;
    this.msgs.push({ ...shown, who, ip });
    if (this.msgs.length > MAX_KEPT) this.msgs.splice(0, this.msgs.length - MAX_KEPT);
    const w = this.waiters; this.waiters = [];
    for (const f of w) f();
    return shown;
  }

  // `reporter` = install hash, `ipk` = its address hash. Only one report per address
  // counts, so one person with made-up install ids can't mute anyone on their own.
  report(id, reporter, ipk, now = Date.now()) {
    this.prune(now);
    const m = this.msgs.find(x => x.id === id);
    if (!m) return { error: "gone", status: 404 };
    const mine = (this.reporting.get(ipk) || []).filter(t => now - t < REPORTS_PER_IP[0]);
    if (mine.length >= REPORTS_PER_IP[1]) return { error: "slow down", status: 429 };
    mine.push(now);
    this.reporting.set(ipk, mine);
    if (reporter === m.who || ipk === m.ip) return { ok: true };   // your own: nothing to do
    let r = this.reports.find(x => x.id === id);
    if (!r) {
      r = { id, t: now, who: m.who, ip: m.ip, name: m.name, text: m.text, by: [], byIp: [] };
      this.reports.push(r);
      if (this.reports.length > MAX_REPORTS) this.reports.shift();
    }
    if (!r.by.includes(reporter) && !r.byIp.includes(ipk)) {
      r.by.push(reporter);
      r.byIp.push(ipk);
    }
    if (r.by.length >= REPORTS_TO_MUTE) {
      this.muted.set(m.who, now + MUTE_MS);
      if (m.ip) this.muted.set(m.ip, now + MUTE_MS);
      // what they said comes off the screen for everyone
      this.msgs = this.msgs.filter(x => x.who !== m.who && (!m.ip || x.ip !== m.ip));
    }
    return { ok: true };
  }

  // A poll: the messages after `after`, held until there's news when there's none yet
  // (`wait`, or a poll this soon after the last one, so an app that asks again at once
  // can't hammer the server). Resolves to [messages, room's last number].
  async poll(who, after, wait, now = Date.now()) {
    this.prune(now);
    const all = after > this.seq ? 0 : after;   // higher than the room's: it started over
    const quick = now - (this.polled.get(who) || -Infinity) < QUICK_MS;
    if ((wait || quick) && !this.since(all).length)
      await this.wait(this.seq, wait ? POLL_MS : QUICK_HOLD_MS);
    this.polled.set(who, Date.now());
    return [this.since(after > this.seq ? 0 : after), this.seq];
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
      const kept = await state.storage.get(["banned", "linked", "off"]);
      if (kept.get("banned")) this.room.banned = new Set(kept.get("banned"));
      if (kept.get("linked")) this.room.linked = new Map(kept.get("linked"));
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
      const [messages, last] = await room.poll(who, after, url.searchParams.get("wait") === "1");
      if (room.off) return json({ error: "off" }, 503);
      return json({ messages, last, off: room.off });
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
      const r = room.report(parseInt(g[1], 10), who, ipk);
      return r.error ? json({ error: r.error }, r.status) : json({ ok: true });
    }
    if (p === "/v1/admin/chat" && req.method === "GET") {
      return json({ off: room.off, banned: room.banned.size,
        reports: room.reports.map(({ id, t, name, text, by, who: w, ip }) =>
          ({ id, t, name, text, reports: by.length, who: w, ip })) });
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
      room.ban(w, b.ban !== false);
      await this.state.storage.put({ banned: [...room.banned], linked: [...room.linked] });
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
