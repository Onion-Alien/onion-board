// Sounds from other sites, in the store as links: only the name, the link and its
// category are kept here, never the file (the app plays and downloads it from the site,
// as if the link had been pasted). Each cron run reads one page of one site, so a run
// stays inside the free plan's limits; the trending page is read every run.
//
// What's synced is live at once and votes, reports and the owner's review work on it as
// on any other sound; a rejected or reported one is never brought back by a later sync.
// Anyone can put a sound on Myinstants, so a name with a link or one of the owner's blocked
// words (words.js) is left out, as it would be from someone sharing it here.

export const MYINSTANTS = "https://www.myinstants.com";
// Myinstants' categories, and the store's own name for each
const MI_CATS = { games: "games", memes: "memes", movies: "movies", music: "music",
  politics: "politics", pranks: "pranks", reactions: "reactions", sports: "sports",
  television: "tv", viral: "viral" };
const MI_PAGES = 5;                  // pages per category (36 sounds each)
const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) " +
  "Chrome/140.0 Safari/537.36";
const BUTTON = /onclick="play\('(\/media\/sounds\/[^']+?\.mp3)'[\s\S]*?class="instant-link[^"]*"[^>]*>([^<]+)<\/a>/g;

// every page one sync cycle reads, in order: [what, url, category]
export function jobs() {
  const out = [];
  for (let page = 1; page <= MI_PAGES; page++)
    for (const [slug, cat] of Object.entries(MI_CATS))
      out.push(["myinstants", `${MYINSTANTS}/en/categories/${slug}/us/?page=${page}`, cat, page]);
  return out;
}

function unescape(s) {
  return s.replace(/&(amp|lt|gt|quot|#39|#x27);/g, (_, e) =>
    ({ amp: "&", lt: "<", gt: ">", quot: '"', "#39": "'", "#x27": "'" })[e]);
}

// a Myinstants page's sound buttons: [{ title, link }]
export function parseMyinstants(html) {
  const out = [], seen = new Set();
  for (const m of html.matchAll(BUTTON)) {
    if (seen.has(m[1])) continue;
    seen.add(m[1]);
    out.push({ title: unescape(m[2]).trim(), link: MYINSTANTS + m[1] });
  }
  return out;
}

async function page(url, fetcher) {
  const r = await fetcher(url, { headers: { "user-agent": UA, accept: "text/html" } });
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.text();
}

// one cron run: the trending page (the store's Trending order), then the next page of
// the cycle. `tools` = index.js's helpers (sha256, linkKey, cleanName, now, logAction, refuse).
export async function syncStep(env, tools, fetcher = fetch) {
  const { sha256, linkKey, cleanName, now, logAction, refuse } = tools;
  const blocked = String(env.CHAT_BLOCK || "").split(",");
  const state = await env.DB.prepare("SELECT value FROM sync WHERE key = 'myinstants'").first();
  const [cursor, cycles] = (state?.value || "0:0").split(":").map(n => parseInt(n) || 0);
  const all = jobs();
  const [, url, cat, pageNo] = all[cursor % all.length];
  const t = now();
  // the first cycle fills the store: it doesn't bury people's uploads under New
  const created = cycles ? t : t - 30 * 86400;
  let added = 0;

  async function upsert(hits, { cat = "", hot = 0, rankFrom = 0 }) {
    const stmts = [];
    for (const [i, h] of hits.entries()) {
      const key = linkKey(h.link);
      const name = cleanName(h.title);
      if (!key || !name || refuse(name, blocked)) continue;
      const pop = cat ? Math.max(0, 1000 - (rankFrom + i) * 5) : 0;
      stmts.push(env.DB.prepare(
        "INSERT INTO sounds (id, name, tags, ext, link, size, sha256, author, uploader, ip, " +
        "status, created, cat, source, hot, pop) VALUES (?, ?, ?, 'link', ?, 0, ?, 'Myinstants', " +
        "'sync', 'sync', 'live', ?, ?, 'myinstants', ?, ?) ON CONFLICT (sha256) DO UPDATE SET " +
        "cat = CASE WHEN sounds.cat = '' THEN excluded.cat ELSE sounds.cat END, " +
        "tags = CASE WHEN sounds.tags = '' THEN excluded.tags ELSE sounds.tags END, " +
        "hot = max(sounds.hot, excluded.hot), pop = max(sounds.pop, excluded.pop)")
        .bind((await sha256(crypto.randomUUID())).slice(0, 12), name, cat, "https://" + key,
              await sha256("link:" + key), created - i, cat, hot ? hot - i * 20 : 0, pop));
    }
    if (!stmts.length) return;
    // a new row gets the next rowid; an updated one keeps its own (counting the table would
    // read every row, twice a run)
    const last = async () => (await env.DB.prepare("SELECT max(rowid) AS n FROM sounds").first()).n || 0;
    const before = await last();
    await env.DB.batch(stmts);
    added += await last() - before;
  }

  // Trending: what's hot there now, fading by a tenth each run once it isn't
  await env.DB.prepare("UPDATE sounds SET hot = hot * 9 / 10 WHERE hot > 0").run();
  try {
    await upsert(parseMyinstants(await page(`${MYINSTANTS}/en/index/us/`, fetcher)), { hot: 1000 });
  } catch (e) {
    await logAction(env, "sync", { detail: `myinstants trending failed: ${e.message || e}` });
  }
  let note;
  try {
    const hits = parseMyinstants(await page(url, fetcher));
    await upsert(hits, { cat, rankFrom: (pageNo - 1) * 36 });
    note = `myinstants ${cat} page ${pageNo}: ${hits.length} read, ${added} new`;
  } catch (e) {
    note = `myinstants ${cat} page ${pageNo} failed: ${e.message || e}`;
  }
  const next = cursor + 1;
  await env.DB.prepare("INSERT INTO sync (key, value) VALUES ('myinstants', ?) " +
    "ON CONFLICT (key) DO UPDATE SET value = excluded.value")
    .bind(`${next % all.length}:${cycles + (next >= all.length ? 1 : 0)}`).run();
  if (added || note.includes("failed")) await logAction(env, "sync", { detail: note });
  return { note, added };
}
