// Run: node --test test/
import test from "node:test";
import assert from "node:assert/strict";
import { Room, clean, nameFor, refuse, sha256 } from "../src/chat.js";

const W = "a".repeat(64), W2 = "b".repeat(64);

test("text is tidied and links are refused", () => {
  assert.equal(clean("  hi‮\n\tthere  "), "hi there");
  for (const bad of ["see https://x.y", "www.evil.com", "join discord.gg/abc", "a.com/x", "evil.xyz"])
    assert.equal(refuse(bad), "no links", bad);
  for (const ok of ["lol", "i hate mondays.", "wait... what", "3.5 is fine"])
    assert.equal(refuse(ok), "", ok);
  assert.equal(refuse("x".repeat(281)), "too long");
  assert.equal(refuse(""), "empty");
  assert.equal(refuse("big bad-word here", ["badword"]), "not allowed");
});

test("names are stable for a hash and look like two words", async () => {
  const h = await sha256("x");
  assert.equal(nameFor(h), nameFor(h));
  assert.match(nameFor(h), /^[A-Z][a-z]+ [A-Z][a-z]+$/);
  assert.notEqual(nameFor(h, 1), nameFor(h));
});

test("nobody shares a name, and a session keeps its own", async () => {
  const r = new Room();
  const same = "ab".repeat(32);   // two sessions whose hashes start the same
  const a = r.nameOf("abababab", same);
  const b = r.nameOf("cdcdcdcd", same);
  assert.notEqual(a, b);
  assert.equal(r.nameOf("abababab", same), a);
  const seen = new Set();
  for (let i = 0; i < 300; i++) seen.add(r.nameOf(String(i).padStart(8, "0"), await sha256(`s${i}`)));
  assert.equal(seen.size, 300);   // 2862 names, and a taken one moves on to the next
});

test("rate limit, repeats, ip limit", () => {
  const r = new Room();
  assert.ok(r.say(W, "ip", "one", 10_000).ok);
  assert.equal(r.say(W, "ip", "two", 10_500).error, "slow down");
  assert.equal(r.say(W, "ip", "ONE", 12_000).error, "repeat");
  assert.ok(r.say(W, "ip", "three", 12_000).ok);
  const r2 = new Room();
  let t = 100_000, n = 0;
  for (let i = 0; i < 70; i++) {
    const out = r2.say(`${i}`.padStart(64, "0"), "same-ip", `m${i}`, (t += 10));
    if (out.ok) n++;
  }
  assert.equal(n, 60);
});

test("history is capped and polls see only newer messages", () => {
  const r = new Room();
  for (let i = 0; i < 80; i++) {
    const s = r.say(W, "ip", `m${i}`, 1_000_000 + i * 4000);
    r.push(s.msg, "u", "N");
  }
  assert.equal(r.msgs.length, 60);
  assert.equal(r.since(75).length, 5);
  assert.ok(!("who" in r.since(0)[0]));
});

test("3 reports mute the author and clear their lines; ban and off work", () => {
  const r = new Room();
  const s = r.say(W, "ip", "rude", 5_000);
  const m = r.push(s.msg, "u", "N");
  r.push(r.say(W2, "ip2", "fine", 5_000).msg, "v", "M");
  assert.ok(r.report(m.id, "p1", "i1", 6_000).ok); assert.ok(r.report(m.id, "p1", "i1", 6_000).ok);
  assert.equal(r.muted.size, 0);
  r.report(m.id, "p2", "i2", 6_000); r.report(m.id, "p3", "i3", 6_000);
  assert.equal(r.say(W, "ip", "again", 9_000).error, "muted");
  assert.equal(r.say(W, "ip", "later", 5_000 + 3_700_000).ok, true);
  assert.equal(r.msgs.length, 1);
  r.banned.add(W2);
  assert.equal(r.say(W2, "ip2", "hi", 99_000).error, "banned");
  r.off = true;
  assert.equal(r.say("c".repeat(64), "ip3", "hi", 99_000).error, "off");
  assert.equal(r.report(9999, "p1", "i1").error, "gone");
});

test("one person with made-up install ids can't mute anyone", () => {
  const r = new Room();
  const m = r.push(r.say(W, "ip", "hello everyone", 5_000).msg, "u", "N");
  for (const fake of ["f1", "f2", "f3", "f4", "f5"]) assert.ok(r.report(m.id, fake, "troll-ip", 6_000).ok);
  assert.equal(r.muted.size, 0);
  assert.equal(r.msgs.length, 1);
  assert.ok(r.say(W, "ip", "still here", 9_000).ok);
  // reporting yourself counts for nothing either
  r.report(m.id, W, "other", 9_500); r.report(m.id, "x", "ip", 9_500);
  assert.equal(r.muted.size, 0);
});

test("a mute covers the address, so a new install id doesn't get round it", () => {
  const r = new Room();
  const m = r.push(r.say(W, "troll-ip", "rude", 5_000).msg, "u", "N");
  for (const [p, i] of [["p1", "i1"], ["p2", "i2"], ["p3", "i3"]]) r.report(m.id, p, i, 6_000);
  assert.equal(r.say(W2, "troll-ip", "new me", 9_000).error, "muted");
  assert.ok(r.say(W2, "elsewhere", "hi", 9_000).ok);
});

test("reports are rate-limited per address", () => {
  const r = new Room();
  let t = 1_000_000;
  const ids = [];
  for (let i = 0; i < 12; i++)
    ids.push(r.push(r.say(`${i}`.padStart(64, "0"), `ip${i}`, `m${i}`, (t += 10)).msg, "u", "N").id);
  const out = ids.map(id => r.report(id, "p1", "one-ip", t + 1));
  assert.equal(out.filter(o => o.ok).length, 10);
  assert.equal(out[10].error, "slow down");
  assert.ok(r.report(ids[11], "p1", "one-ip", t + 600_001).ok);   // ten minutes on: fine again
});

test("a ban covers the addresses the install spoke from, and lifting it frees them", () => {
  const r = new Room();
  r.push(r.say(W, "home", "a", 5_000).msg, "u", "N");
  r.push(r.say(W, "phone", "b", 7_000).msg, "u", "N");
  r.push(r.say(W2, "elsewhere", "c", 7_000).msg, "v", "M");
  assert.equal(r.ban(W), 3);
  assert.equal(r.msgs.length, 1);
  assert.equal(r.say("c".repeat(64), "home", "new id", 9_000).error, "banned");
  r.ban(W, false);
  assert.equal(r.banned.size, 0);
  assert.ok(r.say("c".repeat(64), "home", "back", 11_000).ok);
});

test("rate-limit records are tidied, so new install ids can't fill the memory", () => {
  const r = new Room();
  let t = 0;
  for (let i = 0; i < 5000; i++) r.say(`id${i}`, `ip${i}`, `m${i}`, (t += 20));
  assert.ok(r.last.size < 5000 && r.ips.size < 5000);
  r.say("late", "late-ip", "hi", t + 120_000);
  assert.equal(r.last.size, 1);
  assert.equal(r.ips.size, 1);
});

test("a waiting poll wakes when a message arrives, and gives up on time", async () => {
  const r = new Room();
  const waiting = r.wait(0, 5000);
  r.push(r.say(W, "ip", "hey", 10000000).msg, "u", "N");
  await waiting;
  await r.wait(r.seq, 30);
  await r.wait(99, 30);   // lower seq than the client's: answers at once
});
