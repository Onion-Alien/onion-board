// A key's settings panel in the Stream Deck app. The plugin (bin/actions.js) sends the
// sounds and categories to pick from; picks are saved as the key's settings.
"use strict";

const $ = (id) => document.getElementById(id);
let ws = null;
let uuid = "";
let actionUUID = "";
let settings = {};
let globals = {};
let state = { sounds: [], categories: [], toggles: {} };

function send(event, payload) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ event, context: uuid, action: actionUUID, payload }));
  }
}

function save(change) {
  settings = { ...settings, ...change };
  send("setSettings", settings);
}

function option(value, text, selected) {
  const o = document.createElement("option");
  o.value = value;
  o.textContent = text;
  o.selected = selected;
  return o;
}

function showStatus(p) {
  const box = $("status");
  box.classList.toggle("ok", p.connected);
  box.classList.toggle("bad", !p.connected);
  $("status-text").textContent = p.connected
    ? `Connected to Onion Board${p.version ? ` ${p.version}` : ""}` : "Not connected";
  $("problem").hidden = !p.message;
  $("problem").textContent = p.message || "";
  $("get").hidden = p.problem !== "no_app";
}

function fillSounds() {
  const q = $("search").value.trim().toLowerCase();
  const list = $("sound");
  list.replaceChildren();
  const shown = state.sounds.filter((s) => !q || s.name.toLowerCase().includes(q));
  for (const s of shown) list.append(option(s.id, s.name, s.id === settings.sound));
  // the picked sound is gone from Onion Board (or not loaded yet): keep it in the list
  if (settings.sound && !state.sounds.some((s) => s.id === settings.sound) && !q) {
    list.prepend(option(settings.sound, `${settings.name || "?"} (not found)`, true));
  }
  $("none").hidden = state.sounds.length > 0 || !state.connected;
}

function fillCategories() {
  const sel = $("category");
  const now = settings.category ?? "*";
  sel.replaceChildren(option("*", "The category showing", now === "*"),
                      option("", "Any sound", now === ""));
  for (const c of state.categories) sel.append(option(c, c, c === now));
}

function fillToggles() {
  const sel = $("what");
  const now = settings.what || "live";
  sel.replaceChildren();
  for (const [k, label] of Object.entries(state.toggles)) sel.append(option(k, label, k === now));
}

let lists = "";

function fromPlugin(p) {
  state = p;
  showStatus(p);
  // the plugin sends every 3 s: only rebuild the lists when they changed, so the
  // list doesn't jump back to the top while someone scrolls it
  const now = JSON.stringify([p.sounds, p.categories, p.toggles, p.connected]);
  if (now === lists) return;
  lists = now;
  fillSounds();
  fillCategories();
  fillToggles();
}

$("search").addEventListener("input", fillSounds);
$("sound").addEventListener("change", (e) => {
  const s = state.sounds.find((x) => x.id === e.target.value);
  if (s) save({ sound: s.id, name: s.name });
});
$("category").addEventListener("change", (e) => save({ category: e.target.value }));
$("what").addEventListener("change", (e) => save({ what: e.target.value }));
$("get-link").addEventListener("click", (e) => {
  e.preventDefault();
  send("sendToPlugin", { open: "site" });
});
for (const id of ["port", "token"]) {
  $(id).addEventListener("change", () => {
    globals = { port: $("port").value.trim(), token: $("token").value.trim() };
    send("setGlobalSettings", globals);
    send("sendToPlugin", { refresh: true });
  });
}

// Stream Deck calls this when the panel opens
// eslint-disable-next-line no-unused-vars
function connectElgatoStreamDeckSocket(port, inUUID, registerEvent, info, actionInfo) {
  uuid = inUUID;
  const a = JSON.parse(actionInfo);
  actionUUID = a.action;
  settings = a.payload?.settings || {};
  document.body.dataset.action = actionUUID.split(".").pop();
  ws = new WebSocket(`ws://127.0.0.1:${port}`);
  ws.onopen = () => {
    ws.send(JSON.stringify({ event: registerEvent, uuid }));
    send("getGlobalSettings");
    send("sendToPlugin", { refresh: true });
  };
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.event === "sendToPropertyInspector") fromPlugin(msg.payload);
    else if (msg.event === "didReceiveSettings") settings = msg.payload?.settings || {};
    else if (msg.event === "didReceiveGlobalSettings") {
      globals = msg.payload?.settings || {};
      $("port").value = globals.port || "";
      $("token").value = globals.token || "";
      $("manual").open = Boolean(globals.token);
    }
  };
  // while the panel is open: pick up sounds added in Onion Board, and it starting up
  setInterval(() => send("sendToPlugin", { refresh: true }), 3000);
}
