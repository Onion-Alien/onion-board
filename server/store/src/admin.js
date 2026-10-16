// The owner's review page (/admin): listen to each upload, then approve or reject it.
// The admin token is typed in once and kept in this browser only.
export const ADMIN_PAGE = `<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Store review</title>
<style>
  :root { --bg:#16161c; --panel:#20202a; --hi:#2a2a36; --text:#e8e8ef; --muted:#9a9aab;
          --accent:#8b6cff; --ok:#3fb27f; --bad:#e05a5a; }
  @media (prefers-color-scheme: light) {
    :root { --bg:#f4f4f8; --panel:#fff; --hi:#ececf3; --text:#1d1d26; --muted:#5d5d6e; }
  }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--text);
         font:15px/1.4 "Segoe UI", system-ui, sans-serif; }
  main { max-width:760px; margin:0 auto; padding:16px; }
  h1 { font-size:20px; margin:4px 0 12px; }
  .bar { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:12px; }
  button, input { font:inherit; border-radius:8px; border:0; padding:7px 12px;
                  background:var(--hi); color:var(--text); }
  button { cursor:pointer; } button.on { background:var(--accent); color:#fff; }
  .ok { background:var(--ok); color:#fff; } .bad { background:var(--bad); color:#fff; }
  input { flex:1; min-width:180px; }
  .row { background:var(--panel); border-radius:12px; padding:12px 14px; margin-bottom:8px;
         display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
  .row .name { font-weight:600; flex:1; min-width:160px; word-break:break-word; }
  .muted { color:var(--muted); font-size:13px; }
  .warn { color:var(--bad); font-size:13px; }
  #msg { margin:8px 0; color:var(--muted); }
  a { color:var(--accent); }
</style></head><body><main>
<h1>Sound store review</h1>
<div class="bar" id="login">
  <input id="token" type="password" placeholder="Admin token" autocomplete="off">
  <button class="on" id="save">Sign in</button>
</div>
<div class="bar" id="tabs" hidden>
  <button data-s="pending" class="on">Waiting</button>
  <button data-s="live">Live</button>
  <button data-s="rejected">Rejected</button>
  <button id="out">Forget token</button>
</div>
<div id="msg"></div>
<div id="list"></div>
</main><script>
let token = "", status = "pending", player = null;
try { token = localStorage.getItem("store-admin") || ""; } catch (e) {}
const $ = id => document.getElementById(id);
const api = (path, opts = {}) => fetch(path, { ...opts,
  headers: { ...(opts.headers || {}), authorization: "Bearer " + token } });

function el(tag, attrs = {}, text = "") {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (text) e.textContent = text;
  return e;
}

async function load() {
  $("msg").textContent = "Loading…";
  const r = await api("/v1/admin/queue?status=" + status);
  if (r.status === 401) { $("msg").textContent = "Wrong token."; show(false); return; }
  show(true);
  const { sounds } = await r.json();
  $("msg").textContent = sounds.length ? sounds.length + " sounds" : "Nothing here.";
  const list = $("list");
  list.replaceChildren();
  for (const s of sounds) {
    const row = el("div", { class: "row" });
    const info = el("div", { class: "name" }, s.name);
    info.append(el("div", { class: "muted" },
      (s.author || "Community") + " · " + s.ext + " · " + Math.round(s.size / 1024) + " KB · 👍 " +
      s.up + " 👎 " + s.down + (s.tags.length ? " · " + s.tags.join(", ") : "")));
    if (s.reports) info.append(el("div", { class: "warn" }, "Reported " + s.reports + "×: " + s.why));
    if (s.link) {   // a shared link: open it to check it (nothing is kept but the link)
      info.append(el("div", { class: "muted" }, s.link));
      const open = el("a", { href: s.link, target: "_blank", rel: "noopener noreferrer" }, "Open link");
      row.append(info, open);
    } else {
      const play = el("button", {}, "▶ Play");
      play.onclick = () => listen(s.id, play);
      row.append(info, play);
    }
    if (s.status !== "live") row.append(act(s.id, "approve", "Approve", "ok"));
    if (s.status !== "rejected") row.append(act(s.id, "reject", "Reject", "bad"));
    list.append(row);
  }
}

function act(id, action, label, cls) {
  const b = el("button", { class: cls }, label);
  b.onclick = async () => {
    if (action === "reject" && !confirm("Reject and delete this file?")) return;
    const r = await api("/v1/admin/sounds/" + id, { method: "POST",
      headers: { "content-type": "application/json" }, body: JSON.stringify({ action }) });
    $("msg").textContent = r.ok ? "Done." : "Failed (" + r.status + ").";
    load();
  };
  return b;
}

async function listen(id, btn) {
  if (player) { player.pause(); URL.revokeObjectURL(player.src); player = null; }
  const r = await api("/v1/admin/sounds/" + id + "/file");
  if (!r.ok) { $("msg").textContent = "Couldn't load it."; return; }
  player = new Audio(URL.createObjectURL(await r.blob()));
  player.play();
}

function show(on) { $("tabs").hidden = !on; $("login").hidden = on; }

$("save").onclick = () => {
  token = $("token").value.trim();
  try { localStorage.setItem("store-admin", token); } catch (e) {}
  load();
};
$("out").onclick = () => {
  token = ""; try { localStorage.removeItem("store-admin"); } catch (e) {}
  $("list").replaceChildren(); $("msg").textContent = ""; show(false);
};
for (const b of document.querySelectorAll("#tabs [data-s]")) b.onclick = () => {
  status = b.dataset.s;
  for (const o of document.querySelectorAll("#tabs [data-s]")) o.classList.toggle("on", o === b);
  load();
};
if (token) load();
</script></body></html>`;
