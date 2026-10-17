// Shared sounds keep only the sound: tags and pictures are taken out (src/strip.js).
import test from "node:test";
import assert from "node:assert/strict";
import { stripAudio, crc } from "../src/strip.js";
import { audioType } from "../src/audio.js";

const enc = s => new TextEncoder().encode(s);
const cat = (...parts) => {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let o = 0;
  for (const p of parts) { out.set(p, o); o += p.length; }
  return out;
};
const has = (b, s) => Buffer.from(b).includes(Buffer.from(s));
const u32le = n => { const b = new Uint8Array(4); new DataView(b.buffer).setUint32(0, n, true); return b; };

const FRAME = 417;
function frames(n = 3) {
  const b = new Uint8Array(n * FRAME);
  for (let i = 0; i < n; i++) b.set([0xff, 0xfb, 0x90, 0x00], i * FRAME);
  return b;
}
function id3(text) {
  const t = enc(text), len = t.length;
  return cat(new Uint8Array([0x49, 0x44, 0x33, 3, 0, 0, (len >> 21) & 127, (len >> 14) & 127,
                             (len >> 7) & 127, len & 127]), t);
}

test("an MP3's ID3v2, APE and ID3v1 tags are taken out, its frames kept", () => {
  const v1 = new Uint8Array(128); v1.set(enc("TAGSecret Name"));
  const apeItems = enc("Artist\0Secret Name");
  const apeFooter = cat(enc("APETAGEX"), u32le(2000), u32le(apeItems.length + 32), u32le(1),
                        u32le(0), new Uint8Array(8));
  const f = frames();
  const out = stripAudio(cat(id3("TPE1 Secret Name"), f, apeItems, apeFooter, v1), "mp3");
  assert.deepEqual(out, f);
  assert.equal(audioType(out), "mp3");
  assert.equal(stripAudio(f, "mp3"), f);   // nothing to take out: the same file
});

function wav(extra) {
  const fmt = new Uint8Array(24); fmt.set(enc("fmt ")); const d = new DataView(fmt.buffer);
  d.setUint32(4, 16, true); d.setUint16(8, 1, true); d.setUint16(10, 1, true);
  d.setUint32(12, 44100, true); d.setUint32(16, 88200, true); d.setUint16(20, 2, true); d.setUint16(22, 16, true);
  const data = cat(enc("data"), u32le(4000), new Uint8Array(4000));
  const body = cat(enc("WAVE"), fmt, ...extra, data);
  return cat(enc("RIFF"), u32le(body.length), body);
}

test("a WAV keeps only its format and sound chunks", () => {
  const list = cat(enc("LIST"), u32le(17), enc("INFOIART Secret N"), new Uint8Array(1));   // odd: padded
  const out = stripAudio(wav([list]), "wav");
  assert.deepEqual(out, wav([]));
  assert.ok(!has(out, "Secret"));
  assert.equal(new DataView(out.buffer).getUint32(4, true), out.length - 8);
  assert.equal(audioType(out), "wav");
});

function block(type, body, last = false) {
  return cat(new Uint8Array([type | (last ? 0x80 : 0), body.length >> 16, (body.length >> 8) & 255,
                             body.length & 255]), body);
}

test("a FLAC keeps STREAMINFO and SEEKTABLE, its comments and pictures go", () => {
  const audio = cat(new Uint8Array([0xff, 0xf8, 0x69, 0x08]), new Uint8Array(200));
  const info = new Uint8Array(34), seek = new Uint8Array(18);
  const b = cat(enc("fLaC"), block(0, info), block(4, enc("ARTIST=Secret Name")), block(3, seek),
                block(6, enc("a picture")), block(1, new Uint8Array(10), true), audio);
  const out = stripAudio(b, "flac");
  assert.deepEqual(out, cat(enc("fLaC"), block(0, info), block(3, seek, true), audio));
  assert.equal(audioType(out), "flac");
});

function page(packets, { first = false, seq = 0 } = {}) {
  const segs = [];
  for (const p of packets) {
    let n = p.length;
    for (; n >= 255; n -= 255) segs.push(255);
    segs.push(n);
  }
  const head = new Uint8Array(27 + segs.length);
  head.set(enc("OggS")); head[5] = first ? 2 : 0;
  new DataView(head.buffer).setUint32(18, seq, true);
  head[26] = segs.length; head.set(segs, 27);
  const pg = cat(head, ...packets);
  new DataView(pg.buffer).setUint32(22, crc(pg, 0, pg.length), true);
  return pg;
}
const comments = (...items) => cat(u32le(6), enc("vendor"), u32le(items.length),
  ...items.flatMap(s => [u32le(enc(s).length), enc(s)]));

test("an Ogg's comments are blanked in place, with good checksums", () => {
  const ident = cat(new Uint8Array([1]), enc("vorbis"), new Uint8Array(23));
  const tags = cat(new Uint8Array([3]), enc("vorbis"), comments("ARTIST=Secret Name", "nokey"),
                   new Uint8Array([1]));
  const setup = cat(new Uint8Array([5]), enc("vorbis"), new Uint8Array(300));
  const b = cat(page([ident], { first: true }), page([tags, setup], { seq: 1 }),
                page([new Uint8Array(400)], { seq: 2 }));
  const out = stripAudio(b, "ogg");
  assert.equal(out.length, b.length);
  assert.ok(!has(out, "Secret") && !has(out, "nokey"));
  assert.ok(has(out, "ARTIST=           ") && has(out, "vendor"));
  for (let i = 0; i < out.length;) {   // every page's checksum still right
    const segs = out[i + 26];
    let len = 27 + segs;
    for (let k = 0; k < segs; k++) len += out[i + 27 + k];
    const pg = out.slice(i, i + len), want = new DataView(pg.buffer).getUint32(22, true);
    pg.fill(0, 22, 26);
    assert.equal(crc(pg, 0, len), want);
    i += len;
  }
  assert.equal(audioType(out), "ogg");
});

test("an Opus file's tags are blanked; a file it can't read is left as it was", () => {
  const head = cat(enc("OpusHead"), new Uint8Array(11));
  const tags = cat(enc("OpusTags"), comments("TITLE=Secret Name"));
  const b = cat(page([head], { first: true }), page([tags], { seq: 1 }), page([new Uint8Array(100)], { seq: 2 }));
  const out = stripAudio(b, "ogg");
  assert.ok(!has(out, "Secret") && out.length === b.length);
  const junk = enc("fLaC\0\0");
  assert.equal(stripAudio(junk, "flac"), junk);
});
