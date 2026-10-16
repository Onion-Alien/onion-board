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

test("names are stable for a hash and look like names", async () => {
  const h = await sha256("x");
  assert.equal(nameFor(h), nameFor(h));
  assert.match(nameFor(h), /^[A-Z][a-z]+[A-Z][a-z]+\d\d$/);
});

test("rate limit, repeats, ip limit", () => {
  const r = new Room();
  assert.ok(r.say(W, 1, "ip", "one", 10_000).ok);
  assert.equal(r.say(W, 1, "ip", "two", 10_500).error, "slow down");
  assert.equal(r.say(W, 1, "ip", "ONE", 12_000).error, "repeat");
  assert.ok(r.say(W, 1, "ip", "three", 12_000).ok);
  const r2 = new Room();
  let t = 100_000, n = 0;
  for (let i = 0; i < 70; i++) {
    const out = r2.say(`${i}`.padStart(64, "0"), 1, "same-ip", `m${i}`, (t += 10));
    if (out.ok) n++;
  }
  assert.equal(n, 60);
});

test("history is capped and polls see only newer messages", () => {
  const r = new Room();
  for (let i = 0; i < 80; i++) {
    const s = r.say(W, 1, "ip", `m${i}`, 1_000_000 + i * 4000);
    r.push(s.msg, "u", "N");
  }
  assert.equal(r.msgs.length, 60);
  assert.equal(r.since(75).length, 5);
  assert.ok(!("who" in r.since(0)[0]));
});

test("3 reports mute the author and clear their lines; ban and off work", () => {
  const r = new Room();
  const s = r.say(W, 1, "ip", "rude", 5_000);
  const m = r.push(s.msg, "u", "N");
  r.push(r.say(W2, 1, "ip2", "fine", 5_000).msg, "v", "M");
  assert.ok(r.report(m.id, "p1", 6_000).ok); assert.ok(r.report(m.id, "p1", 6_000).ok);
  assert.equal(r.muted.size, 0);
  r.report(m.id, "p2", 6_000); r.report(m.id, "p3", 6_000);
  assert.equal(r.say(W, 1, "ip", "again", 9_000).error, "muted");
  assert.equal(r.say(W, 1, "ip", "later", 5_000 + 3_700_000).ok, true);
  assert.equal(r.msgs.length, 1);
  r.banned.add(W2);
  assert.equal(r.say(W2, 1, "ip2", "hi", 99_000).error, "banned");
  r.off = true;
  assert.equal(r.say("c".repeat(64), 1, "ip3", "hi", 99_000).error, "off");
  assert.equal(r.report(9999, "p1").error, "gone");
});

test("a waiting poll wakes when a message arrives, and gives up on time", async () => {
  const r = new Room();
  const waiting = r.wait(0, 5000);
  r.push(r.say(W, 1, "ip", "hey", 10000000).msg, "u", "N");
  await waiting;
  await r.wait(r.seq, 30);
  await r.wait(99, 30);   // lower seq than the client's: answers at once
});
