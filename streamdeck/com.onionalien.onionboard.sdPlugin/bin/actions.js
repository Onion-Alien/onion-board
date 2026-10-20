// The plugin's keys: what each does when pressed, and keeping them up to date with
// Onion Board (a playing sound lights up its key, a switch shows on or off).
// `send(message)` goes to Stream Deck; plugin.js connects it. Tests drive this directly.
import { OnionBoard, PROBLEMS, SITE, TOGGLES, keyTitle, soundImage } from "./onionboard.js";

export const UUID = "com.onionalien.onionboard";
export const PLAY = `${UUID}.play`;
export const STOP = `${UUID}.stop`;
export const RANDOM = `${UUID}.random`;
export const TOGGLE = `${UUID}.toggle`;

export const POLL_MS = 1000;        // how often the keys ask what's playing
export const IDLE_POLL_MS = 3000;   // …while Onion Board can't be reached
export const SOUNDS_MS = 10000;     // how often the sound list (names, colours) is fetched

export class Plugin {
  constructor(send, { board = new OnionBoard(), timers = globalThis } = {}) {
    this.send = send;
    this.board = board;
    this.timers = timers;
    this.keys = new Map();        // context → { action, settings }
    this.shown = new Map();       // context → what was last drawn (so nothing is sent twice)
    this.sounds = new Map();      // id → { id, name, color, categories, look }
    this.cards = new Map();       // "id|look|playing" → the pad as Onion Board draws it
    this.categories = [];
    this.soundsAt = 0;
    this.status = null;
    this.problem = null;
    this.timer = null;
    this.busy = false;
  }

  // ------------------------------------------------------------------ Stream Deck's events

  async handle(msg) {
    const { event, context, action, payload } = msg;
    switch (event) {
      case "willAppear":
        this.keys.set(context, { action, settings: payload?.settings || {} });
        this.shown.delete(context);
        this.start();
        // not asked Onion Board yet: the first tick draws it (a switch would show "off" first)
        if (this.status !== null || this.problem !== null) await this.draw(context);
        break;
      case "willDisappear":
        this.keys.delete(context);
        this.shown.delete(context);
        if (!this.keys.size) this.stop();
        break;
      case "didReceiveSettings":
        if (this.keys.has(context)) {
          this.keys.get(context).settings = payload?.settings || {};
          this.shown.delete(context);
          await this.draw(context);
        }
        break;
      case "titleParametersDidChange": {
        // a title the user typed wins: stop writing the sound's name / on-off over it
        const key = this.keys.get(context);
        if (key) {
          const ours = this.shown.get(context)?.title;
          const title = payload?.title ?? "";
          key.userTitle = title !== "" && title !== ours;
          if (!title) {
            this.shown.delete(context);
            await this.draw(context);
          }
        }
        break;
      }
      case "didReceiveGlobalSettings":
        this.board.setManual(payload?.settings || {});
        this.soundsAt = 0;
        await this.tick();
        break;
      case "keyDown":
        await this.press(context, action, payload?.settings || {});
        break;
      case "propertyInspectorDidAppear":
      case "sendToPlugin":
        if (event === "sendToPlugin" && payload?.open === "site") {
          this.send({ event: "openUrl", payload: { url: SITE } });
          break;
        }
        this.soundsAt = 0;
        await this.tick();
        this.toInspector(context, action);
        break;
      default:
        break;
    }
  }

  // ------------------------------------------------------------------ pressing a key

  async press(context, action, settings) {
    let res;
    if (action === PLAY) {
      if (!settings.sound) return this.alert(context);
      res = await this.board.call("play", { id: settings.sound });
      if (!res.ok && res.status === 404 && settings.name) {
        res = await this.board.call("play", { name: settings.name });   // the pad was re-made
      }
    } else if (action === STOP) {
      res = await this.board.call("stop");
    } else if (action === RANDOM) {
      const params = settings.category === undefined || settings.category === "*"
        ? {} : { category: settings.category };   // "" is any sound, no category= the one showing
      res = await this.board.call("random", params);
    } else if (action === TOGGLE) {
      const what = TOGGLES[settings.what] ? settings.what : "live";
      res = await this.board.call(what, { on: "toggle" });
      if (res.ok && res.body && typeof res.body[what] === "boolean") {
        this.status = { ...(this.status || {}), [what]: res.body[what] };
      }
    } else {
      return;
    }
    this.problem = res.ok || res.problem === "error" ? null : res.problem;
    if (!res.ok) this.alert(context);
    else if (action === STOP || action === RANDOM) this.send({ event: "showOk", context });
    await this.tick();
  }

  alert(context) {
    this.send({ event: "showAlert", context });
  }

  // ------------------------------------------------------------------ keeping keys current

  start() {
    if (this.timer === null) this.schedule(0);
  }

  stop() {
    if (this.timer !== null) this.timers.clearTimeout(this.timer);
    this.timer = null;
  }

  schedule(ms) {
    this.timer = this.timers.setTimeout(async () => {
      this.timer = null;
      await this.tick();
      if (this.keys.size && this.timer === null) {
        this.schedule(this.problem ? IDLE_POLL_MS : POLL_MS);
      }
    }, ms);
  }

  // Ask Onion Board what's going on, then redraw the keys that changed.
  async tick() {
    if (this.busy) return;
    this.busy = true;
    try {
      const res = await this.board.call("status");
      this.problem = res.ok ? null : res.problem || "error";
      this.status = res.ok ? res.body : null;
      if (res.ok && Date.now() - this.soundsAt > SOUNDS_MS) {
        const list = await this.board.call("sounds");
        const cats = await this.board.call("categories");
        if (list.ok && Array.isArray(list.body)) {
          this.sounds = new Map(list.body.map((s) => [s.id, s]));
          this.soundsAt = Date.now();
          const current = new Set(list.body.map((s) => `${s.id}|${s.look}|`));
          for (const k of [...this.cards.keys()]) {   // a pad changed: its old pictures go
            if (!current.has(k.slice(0, k.lastIndexOf("|") + 1))) this.cards.delete(k);
          }
        }
        if (cats.ok && Array.isArray(cats.body)) this.categories = cats.body;
      }
      for (const context of this.keys.keys()) await this.draw(context);
    } finally {
      this.busy = false;
    }
  }

  async draw(context) {
    const key = this.keys.get(context);
    if (!key) return;
    const { action, settings } = key;
    const look = {};
    if (action === PLAY) {
      const sound = this.sounds.get(settings.sound);
      const playing = Boolean(this.status?.playing?.includes(settings.sound));
      const card = sound?.look && this.problem === null ? await this.card(sound, playing) : null;
      if (card) {   // the pad as it is on the board, its name and all
        look.image = card;
        look.title = "";
      } else {      // Onion Board can't be reached, or it's too old to draw pads
        look.image = soundImage({ color: sound?.color, playing, problem: this.problem });
        look.title = keyTitle(sound?.name || settings.name || "");
      }
    } else if (action === TOGGLE) {
      const what = TOGGLES[settings.what] ? settings.what : "live";
      const on = Boolean(this.status?.[what]);
      look.state = on ? 0 : 1;
      look.title = TOGGLES[what][on ? "on" : "off"];
    }
    const before = this.shown.get(context) || {};
    if (look.image !== undefined && look.image !== before.image) {
      this.send({ event: "setImage", context, payload: { image: look.image, target: 0 } });
    }
    if (look.state !== undefined && look.state !== before.state) {
      this.send({ event: "setState", context, payload: { state: look.state } });
    }
    if (key.userTitle) delete look.title;
    else if (look.title !== undefined && look.title !== before.title) {
      this.send({ event: "setTitle", context, payload: { title: look.title, target: 0 } });
    }
    this.shown.set(context, look);
  }

  // The pad drawn by Onion Board itself (its theme, picture, name): fetched once for each
  // look of it (the sound list's `look` changes when the picture would) and kept.
  async card(sound, playing) {
    const k = `${sound.id}|${sound.look}|${playing ? 1 : 0}`;
    if (!this.cards.has(k)) {
      const res = await this.board.call("key_image", { id: sound.id, playing: playing ? 1 : 0 });
      if (!res.ok || typeof res.body?.image !== "string") return null;
      this.cards.set(k, res.body.image);
    }
    return this.cards.get(k);
  }

  // What the key's settings panel shows: the sounds and categories to pick from, and
  // what's wrong if Onion Board can't be reached.
  toInspector(context, action) {
    this.send({
      event: "sendToPropertyInspector", context, action,
      payload: {
        connected: this.problem === null && this.status !== null,
        version: this.status?.version || "",
        problem: this.problem,
        message: this.problem ? PROBLEMS[this.problem] || PROBLEMS.error : "",
        sounds: [...this.sounds.values()].map((s) => ({
          id: s.id, name: s.name, categories: s.categories || [] })),
        categories: this.categories,
        toggles: Object.fromEntries(Object.entries(TOGGLES).map(([k, v]) => [k, v.label])),
      },
    });
  }
}
