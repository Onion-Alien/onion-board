// Stream Deck starts this with: -port <n> -pluginUUID <id> -registerEvent <name> -info <json>
// No libraries: Node 24 (manifest.json "Nodejs") has WebSocket and fetch built in.
import { Plugin } from "./actions.js";

function arg(name) {
  const i = process.argv.indexOf(`-${name}`);
  return i >= 0 ? process.argv[i + 1] : undefined;
}

const port = arg("port");
const uuid = arg("pluginUUID");
const registerEvent = arg("registerEvent");
if (!port || !uuid || !registerEvent) {
  console.error("Start this from Stream Deck (it passes -port, -pluginUUID and -registerEvent).");
  process.exit(1);
}

const ws = new WebSocket(`ws://127.0.0.1:${port}`);
const plugin = new Plugin((msg) => {
  if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
});

ws.addEventListener("open", () => {
  ws.send(JSON.stringify({ event: registerEvent, uuid }));
  ws.send(JSON.stringify({ event: "getGlobalSettings", context: uuid }));
});
ws.addEventListener("message", async (ev) => {
  let msg;
  try {
    msg = JSON.parse(String(ev.data));
  } catch {
    return;
  }
  try {
    await plugin.handle(msg);
  } catch (err) {
    console.error(err);
  }
});
// Stream Deck closing the socket means it's quitting or reloading the plugin
ws.addEventListener("close", () => process.exit(0));
