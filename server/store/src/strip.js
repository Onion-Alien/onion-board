// A shared sound is handed to everyone who adds it, so nothing but the sound goes with
// it: tags (artist, comments, the software it was made with), cover pictures and any
// other side data a file can carry are taken out, on upload and again when it's served
// (files kept from before this was done get the same).
//
// stripAudio(bytes, ext) is the file without them; it never adds anything, and any file
// it can't read is returned as it was (audio.js has already checked it on upload).

const le32 = (b, i) => (b[i] | b[i + 1] << 8 | b[i + 2] << 16 | b[i + 3] << 24) >>> 0;
const tag = (b, i, s) => [...s].every((c, k) => b[i + k] === c.charCodeAt(0));
const cat = parts => {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let o = 0;
  for (const p of parts) { out.set(p, o); o += p.length; }
  return out;
};

export function stripAudio(b, ext) {
  try {
    if (ext === "mp3") return mp3(b);
    if (ext === "wav") return wav(b);
    if (ext === "flac") return flac(b);
    if (ext === "ogg") return ogg(b);
  } catch {
    // a field that runs off the end: left as it was
  }
  return b;
}

// ID3v2 in front, an APE tag and ID3v1 at the end: only the frames between are kept
function mp3(b) {
  let start = 0, end = b.length;
  if (tag(b, 0, "ID3")) start = 10 + (b[6] << 21 | b[7] << 14 | b[8] << 7 | b[9]) + (b[5] & 0x10 ? 10 : 0);
  if (end - 128 >= start && tag(b, end - 128, "TAG")) end -= 128;
  // an APE tag's footer: "APETAGEX", then its size (items + footer), plus a header if flagged
  if (end - 32 >= start && tag(b, end - 32, "APETAGEX")) {
    const size = le32(b, end - 20), header = b[end - 9] & 0x80 ? 32 : 0;
    if (size + header <= end - start) end -= size + header;
  }
  if (end - 128 >= start && tag(b, end - 128, "TAG")) end -= 128;
  return start === 0 && end === b.length ? b : b.slice(start, end);
}

// only "fmt ", "fact" and "data" chunks are kept (LIST/INFO, bext, id3, iXML... go)
const WAV_KEEP = ["fmt ", "fact", "data"];

function wav(b) {
  const parts = [];
  let i = 12;
  while (i + 8 <= b.length) {
    const id = String.fromCharCode(...b.slice(i, i + 4));
    let n = le32(b, i + 4);
    if (id === "data") n = Math.min(n, b.length - i - 8);
    const step = 8 + n + (n & 1);
    if (WAV_KEEP.includes(id)) parts.push(b.slice(i, Math.min(b.length, i + step)));
    if (id === "data") break;
    i += step;
  }
  const body = cat([new TextEncoder().encode("WAVE"), ...parts]);
  const head = new Uint8Array(8);
  head.set(new TextEncoder().encode("RIFF"));
  new DataView(head.buffer).setUint32(4, body.length, true);
  const out = cat([head, body]);
  return out.length === b.length ? b : out;
}

// only STREAMINFO and SEEKTABLE are kept (comments, pictures, application data go)
function flac(b) {
  const keep = [];
  let i = 4, last = false;
  while (!last) {
    const type = b[i] & 0x7f, n = b[i + 1] << 16 | b[i + 2] << 8 | b[i + 3];
    last = !!(b[i] & 0x80);
    if (type === 0 || type === 3) keep.push(b.slice(i, i + 4 + n));
    i += 4 + n;
    if (i > b.length) return b;
  }
  if (!keep.length || (keep[0][0] & 0x7f) !== 0) return b;
  keep.forEach((k, j) => { k[0] = (k[0] & 0x7f) | (j === keep.length - 1 ? 0x80 : 0); });
  const out = cat([b.slice(0, 4), ...keep, b.slice(i)]);
  return out.length === b.length ? b : out;
}

// Ogg: the comment header's texts are blanked in place (each "KEY=value" keeps its
// length, the value made spaces), and a FLAC-in-Ogg stream's other side blocks become
// padding, so no page changes size; the changed pages get a new checksum.
function ogg(b) {
  const out = b.slice();
  const pages = [];   // [page start, its packet bytes' positions...]
  let i = 0;
  // the header packets: the first page's, and those up to the first audio page
  let packet = [], packets = [], changed = new Set();
  while (i + 27 <= b.length && tag(b, i, "OggS")) {
    const segs = b[i + 26];
    let p = i + 27 + segs;
    const page = { at: i, len: 27 + segs };
    for (let k = 0; k < segs; k++) {
      const n = b[i + 27 + k];
      for (let j = 0; j < n; j++) packet.push([p + j, i]);
      p += n;
      page.len += n;
      if (n < 255) { packets.push(packet); packet = []; }
    }
    pages.push(page);
    i += page.len;
    if (packets.length && packets.length >= headers(b, packets[0])) break;
  }
  if (packets.length < 2) return b;
  const first = packets[0];
  const kind = kindOf(b, first);
  if (!kind) return b;
  for (const pk of packets.slice(1, headers(b, first))) {
    const byte = k => out[pk[k][0]];
    const set = (k, v) => { out[pk[k][0]] = v; changed.add(pk[k][1]); };
    let start = -1;
    if (kind === "vorbis" && byte(0) === 3) start = 7;
    else if (kind === "opus" && tag(b, pk[0][0], "OpusTags")) start = 8;
    else if (kind === "flac") {
      const type = byte(0) & 0x7f;
      if (type === 4) start = 4;
      else if (type !== 0 && type !== 3) {   // a picture, application data...: padding now
        set(0, (byte(0) & 0x80) | 1);
        for (let k = 4; k < pk.length; k++) set(k, 0);
      }
    }
    if (start < 0) continue;
    const u32 = k => (byte(k) | byte(k + 1) << 8 | byte(k + 2) << 16 | byte(k + 3) << 24) >>> 0;
    let k = start;
    k += 4 + u32(k);            // the vendor string (the encoder's name) stays
    const count = u32(k);
    k += 4;
    for (let c = 0; c < count && k + 4 <= pk.length; c++) {
      const len = u32(k);
      k += 4;
      let eq = -1;
      for (let j = 0; j < len && k + j < pk.length; j++) {
        if (eq < 0 && byte(k + j) === 0x3d) eq = j;
        else if (eq >= 0 && byte(k + j) !== 0x20) set(k + j, 0x20);
      }
      if (eq < 0) for (let j = 0; j < len && k + j < pk.length; j++)
        if (byte(k + j) !== 0x20) set(k + j, 0x20);   // no "=": all of it
      k += len;
    }
  }
  if (!changed.size) return b;
  for (const pg of pages) if (changed.has(pg.at)) {
    out.fill(0, pg.at + 22, pg.at + 26);
    new DataView(out.buffer, out.byteOffset).setUint32(pg.at + 22, crc(out, pg.at, pg.len), true);
  }
  return out;
}

// what a stream's first packet says it is: "vorbis", "opus", "flac" or ""
function kindOf(b, pk) {
  if (pk.length < 9) return "";
  if (b[pk[0][0]] === 1 && tag(b, pk[1][0], "vorbis")) return "vorbis";
  if (tag(b, pk[0][0], "OpusHead")) return "opus";
  if (b[pk[0][0]] === 0x7f && tag(b, pk[1][0], "FLAC")) return "flac";
  return "";
}

// how many header packets the stream has, the first one included (anything else: 1,
// so nothing more is read)
function headers(b, pk) {
  const kind = kindOf(b, pk);
  if (kind === "vorbis") return 3;
  if (kind === "opus") return 2;
  if (kind === "flac") return 1 + Math.min(64, b[pk[7][0]] << 8 | b[pk[8][0]]);
  return 1;
}

let TABLE = null;
export function crc(b, at, len) {   // Ogg's CRC-32 (polynomial 0x04c11db7, not reflected)
  if (!TABLE) {
    TABLE = new Uint32Array(256);
    for (let i = 0; i < 256; i++) {
      let r = i << 24;
      for (let j = 0; j < 8; j++) r = r & 0x80000000 ? (r << 1) ^ 0x04c11db7 : r << 1;
      TABLE[i] = r >>> 0;
    }
  }
  let c = 0;
  for (let i = at; i < at + len; i++) c = ((c << 8) ^ TABLE[((c >>> 24) ^ b[i]) & 255]) >>> 0;
  return c;
}
