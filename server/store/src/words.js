// What people may write in the names, tags and descriptions everyone sees: no links,
// none of the owner's blocked words (the BLOCKED_WORDS secret), and nothing too long.
// Sounds' and voices' routes both use it.

const MAX_LEN = 280;

// links of any kind (so no spam, no invites, no pictures): schemes, www., and name.tld/
const LINK = /(https?:|ftp:|file:|data:|javascript:|www\.|\b[a-z0-9-]{2,}\.(com|net|org|io|gg|ly|me|co|tv|xyz|app|dev|ru|to|cc|info|biz|site|online|shop|top|link|click|su|pw|cn|uk)\b|discord\.gg|[a-z0-9-]+\.[a-z]{2,}\/)/i;

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

// whether `text` holds one of the `blocked` words
export function hasBlocked(text, blocked = []) {
  const low = squash(text);
  return blocked.some(w => squash(w) && wordRe(w).test(low));
}

// why `text` can't be shown, or "" when it can
export function refuse(text, blocked = []) {
  if (!text) return "empty";
  if (text.length > MAX_LEN) return "too long";
  if (LINK.test(text)) return "no links";
  if (hasBlocked(text, blocked)) return "not allowed";
  return "";
}
