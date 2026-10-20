// Run: node --test streamdeck/test/   (Node 24, like Stream Deck's own)
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync, rmSync, readFileSync, utimesSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { OnionBoard, keyTitle, readConnection, soundImage, configPath } from
  "../com.onionalien.onionboard.sdPlugin/bin/onionboard.js";
import { Plugin, PLAY, STOP, RANDOM, TOGGLE } from
  "../com.onionalien.onionboard.sdPlugin/bin/actions.js";

const TOKEN = "k".repeat(32);

function tempConfig(cfg) {
  const dir = mkdtempSync(join(tmpdir(), "ob-sd-"));
  const path = join(dir, "config.json");
  if (cfg !== undefined) writeFileSync(path, typeof cfg === "string" ? cfg : JSON.stringify(cfg));
  return { dir, path, done: () => rmSync(dir, { recursive: true, force: true }) };
}

// a stand-in for Onion Board's API: answers like soundboard/control/remote.py
function fakeApp(state = {}) {
  const s = { playing: [], live: true, voice: false, mic: true, hotkeys: true,
              sounds: [{ id: "s0", name: "Airhorn", color: "#ff5c8a", categories: ["Memes"] },
                       { id: "s1", name: "Sad trombone", color: "#1fb6ff", categories: [] }],
              categories: ["Memes"], calls: [], down: false, ...state };
  s.fetch = async (url, opts) => {
    if (s.down) throw new TypeError("fetch failed");
    const u = new URL(url);
    const action = u.pathname.replace("/api/", "");
    const p = Object.fromEntries(u.searchParams);
    s.calls.push([action, p, opts.headers["X-Token"], u.host]);
    const reply = (status, body) => ({ status, ok: status < 400, json: async () => body });
    if (opts.headers["X-Token"] !== TOKEN) return reply(401, { error: "wrong key" });
    if (action === "status") {
      return reply(200, { version: "9.9.9", playing: s.playing, live: s.live, voice: s.voice,
                          mic: s.mic, hotkeys: s.hotkeys });
    }
    if (action === "sounds") return reply(200, s.sounds);
    if (action === "categories") return reply(200, s.categories);
    if (action === "key_image") {
      const m = s.sounds.find((x) => x.id === p.id);
      if (!m) return reply(404, { error: "no such sound" });
      return reply(200, { id: m.id, look: m.look,
                          image: `data:image/png;base64,${m.id}-${m.look}-${p.playing}` });
    }
    if (action === "play") {
      const m = s.sounds.find((x) => x.id === p.id || x.name.toLowerCase() === p.name?.toLowerCase());
      if (!m) return reply(404, { error: "no such sound" });
      s.playing = [m.id];
      return reply(200, { playing: m.id, name: m.name });
    }
    if (action === "stop") { s.playing = []; return reply(200, { stopped: "all" }); }
    if (action === "random") return reply(200, { playing: "s1", name: "Sad trombone" });
    if (["live", "voice", "mic", "hotkeys"].includes(action)) {
      s[action] = p.on === "toggle" ? !s[action] : p.on === "1";
      return reply(200, { [action]: s[action] });
    }
    return reply(404, { error: "unknown" });
  };
  return s;
}

function setup(cfg = { api_enabled: true, api_port: 7575, api_token: TOKEN }, app = fakeApp()) {
  const conf = tempConfig(cfg);
  const sent = [];
  const board = new OnionBoard({ path: conf.path, fetch: app.fetch });
  // no real timers: the tests call tick() themselves
  const timers = { setTimeout: () => 1, clearTimeout: () => {} };
  const plugin = new Plugin((m) => sent.push(m), { board, timers });
  return { plugin, sent, app, conf, board };
}

const appear = (action, context, settings = {}) =>
  ({ event: "willAppear", action, context, payload: { settings } });
const of = (sent, event, context) => sent.filter((m) => m.event === event && m.context === context);

test("finds the port and key in Onion Board's config.json", async () => {
  const c = tempConfig("\uFEFF" + JSON.stringify({ api_enabled: true, api_port: 8000, api_token: "abc" }));
  try {
    assert.deepEqual(await readConnection(c.path), { enabled: true, port: 8000, token: "abc" });
    writeFileSync(c.path, JSON.stringify({ api_port: "x" }));
    assert.deepEqual(await readConnection(c.path), { enabled: false, port: 7474, token: "" });
    writeFileSync(c.path, "{half a file");
    assert.equal(await readConnection(c.path), null);
    assert.equal(await readConnection(join(c.dir, "nope.json")), null);
  } finally {
    c.done();
  }
  assert.match(configPath({ APPDATA: "X:\\appdata" }), /OnionBoard[\\/]config\.json$/);
});

test("says what's wrong: not installed, Remote off, not running, wrong key", async () => {
  const app = fakeApp();
  const none = new OnionBoard({ path: join(tmpdir(), "no-such-dir-ob", "config.json"), fetch: app.fetch });
  assert.equal((await none.call("status")).problem, "no_app");

  const c = tempConfig({ api_enabled: false, api_token: TOKEN });
  try {
    const b = new OnionBoard({ path: c.path, fetch: app.fetch });
    assert.equal((await b.call("status")).problem, "remote_off");
    assert.equal(app.calls.length, 0);   // never knocks while Remote is off

    // turned on in Settings: picked up without restarting Stream Deck
    writeFileSync(c.path, JSON.stringify({ api_enabled: true, api_port: 7575, api_token: TOKEN }));
    utimesSync(c.path, new Date(), new Date(Date.now() + 5000));
    const ok = await b.call("status");
    assert.ok(ok.ok);
    assert.deepEqual(app.calls.at(-1).slice(2), [TOKEN, "127.0.0.1:7575"]);

    app.down = true;
    assert.equal((await b.call("status")).problem, "not_running");
    app.down = false;

    b.setManual({ port: "7575", token: "wrong" });
    assert.equal((await b.call("status")).problem, "bad_key");
    b.setManual({ token: "" });   // emptied: back to reading config.json
    assert.ok((await b.call("status")).ok);
  } finally {
    c.done();
  }
});

test("a Play key shows its sound's name and colour, and lights up while it plays", async () => {
  const { plugin, sent, app, conf } = setup();
  try {
    await plugin.handle(appear(PLAY, "k1", { sound: "s1", name: "Sad trombone" }));
    await plugin.tick();
    assert.equal(of(sent, "setTitle", "k1").at(-1).payload.title, "Sad\ntrombone");
    const idle = of(sent, "setImage", "k1").at(-1).payload.image;
    assert.equal(idle, soundImage({ color: "#1fb6ff" }));

    await plugin.handle({ event: "keyDown", action: PLAY, context: "k1",
                          payload: { settings: { sound: "s1", name: "Sad trombone" } } });
    assert.deepEqual(app.calls.find((c) => c[0] === "play")[1], { id: "s1" });
    assert.equal(of(sent, "setImage", "k1").at(-1).payload.image,
                 soundImage({ color: "#1fb6ff", playing: true }));

    // nothing changed: nothing more is sent to Stream Deck
    const before = sent.length;
    await plugin.tick();
    assert.equal(sent.length, before);

    app.playing = [];
    await plugin.tick();
    assert.equal(of(sent, "setImage", "k1").at(-1).payload.image, idle);
  } finally {
    conf.done();
  }
});

test("a Play key whose pad was made again plays it by name; no sound picked shows an alert", async () => {
  const { plugin, sent, app, conf } = setup();
  try {
    await plugin.handle({ event: "keyDown", action: PLAY, context: "k1",
                          payload: { settings: { sound: "old-id", name: "airhorn" } } });
    assert.deepEqual(app.calls.filter((c) => c[0] === "play").map((c) => c[1]),
                     [{ id: "old-id" }, { name: "airhorn" }]);
    assert.deepEqual(app.playing, ["s0"]);
    await plugin.handle({ event: "keyDown", action: PLAY, context: "k2", payload: { settings: {} } });
    assert.equal(of(sent, "showAlert", "k2").length, 1);
  } finally {
    conf.done();
  }
});

test("Stop, Random and a switch do what they say", async () => {
  const { plugin, sent, app, conf } = setup();
  try {
    app.playing = ["s0"];
    await plugin.handle({ event: "keyDown", action: STOP, context: "a", payload: { settings: {} } });
    assert.deepEqual(app.playing, []);
    assert.equal(of(sent, "showOk", "a").length, 1);

    const random = async (settings) => {
      await plugin.handle({ event: "keyDown", action: RANDOM, context: "r", payload: { settings } });
      return app.calls.filter((c) => c[0] === "random").at(-1)[1];
    };
    assert.deepEqual(await random({}), {});                      // the category showing
    assert.deepEqual(await random({ category: "*" }), {});
    assert.deepEqual(await random({ category: "" }), { category: "" });   // any sound
    assert.deepEqual(await random({ category: "Memes" }), { category: "Memes" });

    await plugin.handle(appear(TOGGLE, "t", { what: "voice" }));
    await plugin.tick();
    assert.deepEqual(of(sent, "setState", "t").at(-1).payload, { state: 1 });   // off
    assert.equal(of(sent, "setTitle", "t").at(-1).payload.title, "Voice\noff");
    await plugin.handle({ event: "keyDown", action: TOGGLE, context: "t",
                          payload: { settings: { what: "voice" } } });
    assert.equal(app.voice, true);
    assert.deepEqual(of(sent, "setState", "t").at(-1).payload, { state: 0 });
    assert.equal(of(sent, "setTitle", "t").at(-1).payload.title, "Voice\non");

    // changed in the app (or by its own hotkey): the key follows
    app.hotkeys = false;
    await plugin.handle(appear(TOGGLE, "h", { what: "hotkeys" }));
    await plugin.tick();
    assert.deepEqual(of(sent, "setState", "h").at(-1).payload, { state: 1 });
  } finally {
    conf.done();
  }
});

test("a title the user typed isn't written over", async () => {
  const { plugin, sent, conf } = setup();
  try {
    await plugin.handle(appear(PLAY, "k", { sound: "s0", name: "Airhorn" }));
    await plugin.tick();
    await plugin.handle({ event: "titleParametersDidChange", context: "k", action: PLAY,
                          payload: { title: "Airhorn" } });   // ours, echoed back
    await plugin.handle({ event: "titleParametersDidChange", context: "k", action: PLAY,
                          payload: { title: "HONK" } });
    const n = of(sent, "setTitle", "k").length;
    plugin.sounds.get("s0").name = "Air horn";
    plugin.shown.delete("k");
    await plugin.draw("k");
    assert.equal(of(sent, "setTitle", "k").length, n);
    await plugin.handle({ event: "titleParametersDidChange", context: "k", action: PLAY,
                          payload: { title: "" } });   // cleared: the sound's name again
    assert.equal(of(sent, "setTitle", "k").at(-1).payload.title, "Air horn");
  } finally {
    conf.done();
  }
});

test("Onion Board closed: keys go grey with a !, the panel says why", async () => {
  const app = fakeApp({ down: true });
  const { plugin, sent, conf } = setup(undefined, app);
  try {
    await plugin.handle(appear(PLAY, "k", { sound: "s0", name: "Airhorn" }));
    await plugin.tick();
    assert.equal(of(sent, "setImage", "k").at(-1).payload.image,
                 soundImage({ color: undefined, problem: "not_running" }));
    assert.equal(of(sent, "setTitle", "k").at(-1).payload.title, "Airhorn");   // from settings
    await plugin.handle({ event: "propertyInspectorDidAppear", action: PLAY, context: "k" });
    const pi = of(sent, "sendToPropertyInspector", "k").at(-1).payload;
    assert.equal(pi.connected, false);
    assert.equal(pi.problem, "not_running");
    assert.match(pi.message, /isn't running/);

    app.down = false;
    await plugin.handle({ event: "sendToPlugin", action: PLAY, context: "k", payload: { refresh: true } });
    const ok = of(sent, "sendToPropertyInspector", "k").at(-1).payload;
    assert.equal(ok.connected, true);
    assert.equal(ok.version, "9.9.9");
    assert.deepEqual(ok.sounds.map((s) => s.name), ["Airhorn", "Sad trombone"]);
    assert.deepEqual(ok.categories, ["Memes"]);
    assert.equal(of(sent, "setImage", "k").at(-1).payload.image, soundImage({ color: "#ff5c8a" }));
  } finally {
    conf.done();
  }
});

test("the last key gone stops asking Onion Board", async () => {
  const { plugin, conf } = setup();
  let cleared = 0;
  plugin.timers = { setTimeout: () => 7, clearTimeout: () => { cleared += 1; } };
  try {
    await plugin.handle(appear(STOP, "a"));
    assert.equal(plugin.timer, 7);
    await plugin.handle({ event: "willDisappear", action: STOP, context: "a" });
    assert.equal(plugin.timer, null);
    assert.equal(cleared, 1);
  } finally {
    conf.done();
  }
});

test("names wrap to fit a key", () => {
  assert.equal(keyTitle("Airhorn"), "Airhorn");
  assert.equal(keyTitle("Sad trombone"), "Sad\ntrombone");
  assert.equal(keyTitle("Bruh"), "Bruh");
  assert.equal(keyTitle("Supercalifragilistic"), "Supercali\nfragilist\nic");
  assert.equal(keyTitle("one two three four five six seven eight nine"), "one two\nthree\nfour fiv…");
  assert.equal(keyTitle(""), "");
});

test("the manifest's pictures and files exist", () => {
  const root = new URL("../com.onionalien.onionboard.sdPlugin/", import.meta.url);
  const m = JSON.parse(readFileSync(new URL("manifest.json", root), "utf8"));
  const exists = (p, exts) => exts.some((e) => {
    try { readFileSync(new URL(p + e, root)); return true; } catch { return false; }
  });
  const pics = [m.Icon, m.CategoryIcon, ...m.Actions.flatMap((a) => [a.Icon, ...a.States.map((s) => s.Image)])];
  for (const p of pics) assert.ok(exists(p, [".svg", ".png"]), p);
  assert.ok(exists(m.CodePath, [""]) && exists(m.PropertyInspectorPath, [""]));
  assert.deepEqual(m.Actions.map((a) => a.UUID), [PLAY, STOP, RANDOM, TOGGLE]);
});

test("a play key shows the pad as Onion Board draws it, and fetches it again only when it changes", async () => {
  const app = fakeApp();
  app.sounds = app.sounds.map((x) => ({ ...x, look: "a1" }));
  const { plugin, sent, conf } = setup(undefined, app);
  try {
    await plugin.handle(appear(PLAY, "k", { sound: "s0", name: "Airhorn" }));
    await plugin.tick();
    assert.equal(of(sent, "setImage", "k").at(-1).payload.image, "data:image/png;base64,s0-a1-0");
    assert.equal(of(sent, "setTitle", "k").at(-1)?.payload.title ?? "", "");   // the name is in the picture
    const asked = () => app.calls.filter(([a]) => a === "key_image").length;
    const n = asked();
    await plugin.tick();
    assert.equal(asked(), n);                                   // kept, not fetched every second
    app.playing = ["s0"];
    await plugin.tick();
    assert.equal(of(sent, "setImage", "k").at(-1).payload.image, "data:image/png;base64,s0-a1-1");
    app.playing = [];
    await plugin.tick();
    assert.equal(of(sent, "setImage", "k").at(-1).payload.image, "data:image/png;base64,s0-a1-0");
    assert.equal(asked(), n + 1);                               // the idle one was kept too
    app.sounds[0] = { ...app.sounds[0], look: "b2" };            // renamed / new picture / theme
    plugin.soundsAt = 0;
    await plugin.tick();
    assert.equal(of(sent, "setImage", "k").at(-1).payload.image, "data:image/png;base64,s0-b2-0");
    assert.ok(![...plugin.cards.keys()].some((k) => k.includes("|a1|")));
    app.down = true;                                            // can't be reached: the grey key
    await plugin.tick();
    assert.equal(of(sent, "setImage", "k").at(-1).payload.image,
                 soundImage({ color: "#ff5c8a", problem: plugin.problem }));
  } finally {
    conf.done();
  }
});
