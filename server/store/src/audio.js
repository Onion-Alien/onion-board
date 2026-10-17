// Is an uploaded file really a sound? Its first bytes alone prove nothing: "ID3" or
// "RIFF....WAVE" in front of a program or a script would pass. So the whole file is
// walked: every MP3 frame, every WAV chunk, every Ogg page and FLAC's header blocks,
// and the parts that aren't sound (tags, cover art, unknown chunks) may only be small.
// Then no text that belongs in a web page, a script or a program may be in it anywhere.
//
// audioType(bytes) is "mp3", "ogg", "wav" or "flac", or "" when it isn't one.

// tags, cover art and other non-sound parts, in all (a song's cover picture can be 1.6 MB)
export const META_MAX = 2 << 20;

// what code looks like; a real sound's bytes don't spell these (lower case compared)
export const CODE_MARKS = ["<script", "<?php", "<html", "<iframe", "<object", "<embed",
  "<!doctype", "javascript:", "vbscript:", "onerror=", "onload=", "powershell", "cmd.exe",
  "wscript", "cscript", "rundll32", "regsvr32", "mshta", "certutil", "invoke-expression",
  "frombase64string", "#!/bin/", "#!/usr/", "this program cannot be run in dos mode",
  "eval(", "exec(", "system(", "subprocess", "import os", "__import__", "document.cookie",
  "xmlhttprequest", "activexobject"];

export function audioType(b) {
  if (!(b instanceof Uint8Array) || b.length < 12) return "";
  let ext = "";
  try {
    ext = isFlac(b) ? "flac" : isOgg(b) ? "ogg" : isWav(b) ? "wav" : isMp3(b) ? "mp3" : "";
  } catch {
    return "";   // a length that runs off the end, a bad field: not a sound
  }
  return ext && !hasCode(b) ? ext : "";
}

const tag = (b, i, s) => [...s].every((c, k) => b[i + k] === c.charCodeAt(0));
const le32 = (b, i) => (b[i] | b[i + 1] << 8 | b[i + 2] << 16 | b[i + 3] << 24) >>> 0;
const le16 = (b, i) => b[i] | b[i + 1] << 8;

// ------------------------------------------------------------------ code inside

export function hasCode(b) {
  const lc = new Uint8Array(b.length);   // ASCII letters in lower case
  for (let i = 0; i < b.length; i++) { const c = b[i]; lc[i] = c >= 65 && c <= 90 ? c + 32 : c; }
  for (const mark of CODE_MARKS) {
    const m = [...mark].map(c => c.charCodeAt(0));
    for (let i = lc.indexOf(m[0]); i >= 0 && i <= lc.length - m.length; i = lc.indexOf(m[0], i + 1)) {
      let k = 1;
      while (k < m.length && lc[i + k] === m[k]) k++;
      if (k === m.length) return true;
    }
  }
  return false;
}

// ------------------------------------------------------------------ MP3

const BITRATES = {   // kbit/s by [version 1 or 2][layer]
  "1,1": [0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448],
  "1,2": [0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384],
  "1,3": [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320],
  "2,1": [0, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256],
  "2,2": [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],
  "2,3": [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],
};

// the length of the MPEG audio frame starting at i, or 0 when there isn't one
export function frameLen(b, i) {
  if (i + 4 > b.length || b[i] !== 0xff || (b[i + 1] & 0xe0) !== 0xe0) return 0;
  const ver = (b[i + 1] >> 3) & 3;        // 3: MPEG 1, 2: MPEG 2, 0: MPEG 2.5
  const layer = 4 - ((b[i + 1] >> 1) & 3);   // 1, 2 or 3 (4: reserved)
  const bi = b[i + 2] >> 4, si = (b[i + 2] >> 2) & 3, pad = (b[i + 2] >> 1) & 1;
  if (ver === 1 || layer === 4 || bi === 0 || bi === 15 || si === 3) return 0;
  const rate = [44100, 48000, 32000][si] / (ver === 3 ? 1 : ver === 2 ? 2 : 4);
  const kbps = BITRATES[`${ver === 3 ? 1 : 2},${layer}`][bi];
  if (layer === 1) return Math.floor(12 * kbps * 1000 / rate + pad) * 4;
  const per = layer === 3 && ver !== 3 ? 72 : 144;
  return Math.floor(per * kbps * 1000 / rate) + pad;
}

function isMp3(b) {
  let i = 0, meta = 0, frames = 0;
  if (tag(b, 0, "ID3")) {   // an ID3v2 tag: its size is 4 bytes of 7 bits
    if (b[3] > 4 || (b[6] | b[7] | b[8] | b[9]) & 0x80) return false;
    i = 10 + (b[6] << 21 | b[7] << 14 | b[8] << 7 | b[9]) + (b[5] & 0x10 ? 10 : 0);
    meta = i;
  }
  while (i < b.length) {
    const n = frameLen(b, i);
    if (n && i + n <= b.length) { frames++; i += n; continue; }
    if (n && frames) { i = b.length; break; }   // the last frame cut short: fine
    if (tag(b, i, "TAG") && b.length - i === 128) { meta += 128; break; }   // ID3v1
    if (tag(b, i, "APETAGEX")) { meta += b.length - i; break; }   // an APE tag, to the end
    meta++;          // something else: skipped a byte at a time, and it counts
    i++;
    if (meta > META_MAX) return false;
  }
  return frames >= 2 && meta <= META_MAX;
}

// ------------------------------------------------------------------ WAV

const WAV_FORMATS = [1, 3, 6, 7, 0xfffe];   // PCM, float, A-law, mu-law, extensible

function isWav(b) {
  if (!tag(b, 0, "RIFF") || !tag(b, 8, "WAVE")) return false;
  let i = 12, meta = 12, fmt = false, data = false;
  while (i + 8 <= b.length) {
    const id = String.fromCharCode(...b.slice(i, i + 4));
    if (!/^[\x20-\x7e]{4}$/.test(id)) return false;
    let n = le32(b, i + 4);
    if (id === "data") {
      if (!fmt) return false;
      n = Math.min(n, b.length - i - 8);   // a recorder may leave the length unset
      data = n > 0;
    } else {
      if (i + 8 + n > b.length) return false;
      meta += 8 + n;
      if (id === "fmt ") {
        if (n < 16 || !WAV_FORMATS.includes(le16(b, i + 8))) return false;
        const ch = le16(b, i + 10), rate = le32(b, i + 12);
        if (ch < 1 || ch > 8 || rate < 4000 || rate > 384000) return false;
        fmt = true;
      }
    }
    i += 8 + n + (n & 1);
    if (meta > META_MAX) return false;
  }
  return data && b.length - i < 8;
}

// ------------------------------------------------------------------ Ogg

function isOgg(b) {
  if (!tag(b, 0, "OggS")) return false;
  let i = 0, sound = false;
  while (i < b.length) {   // page after page, to the very end
    if (!tag(b, i, "OggS") || b[i + 4] !== 0) return false;
    const segs = b[i + 26];
    let n = 27 + segs;
    for (let k = 0; k < segs; k++) n += b[i + 27 + k];
    if (i + n > b.length) return false;
    if (b[i + 5] & 2) {   // a stream's first page says its codec: Vorbis, Opus or FLAC
      const p = i + 27 + segs;   // (or Skeleton, the index some files carry, never video)
      if (tag(b, p, "\x01vorbis") || tag(b, p, "OpusHead") || tag(b, p, "\x7fFLAC")) sound = true;
      else if (!tag(b, p, "fishead\0")) return false;
    }
    i += n;
  }
  return sound;
}

// ------------------------------------------------------------------ FLAC

function isFlac(b) {
  if (!tag(b, 0, "fLaC")) return false;
  let i = 4, last = false, blocks = 0;
  while (!last) {
    if (i + 4 > b.length) return false;
    const type = b[i] & 0x7f, n = b[i + 1] << 16 | b[i + 2] << 8 | b[i + 3];
    last = !!(b[i] & 0x80);
    if (type === 127 || (blocks === 0 && (type !== 0 || n !== 34))) return false;
    i += 4 + n;
    blocks++;
    if (i > META_MAX) return false;
  }
  return i + 2 <= b.length && b[i] === 0xff && (b[i + 1] & 0xfe) === 0xf8;   // a frame
}
