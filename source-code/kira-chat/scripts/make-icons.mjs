// Icons are code, not binaries: the repo has no committed image, and the tray icon took the same
// decision. This writes four PNGs the manifest and iOS ask for. Nothing here is imported by the app —
// `npm run build` runs it first, into `public/icons/`, which Vite copies into the bundle.
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { deflateSync } from "node:zlib";

const INK = [0x0f, 0x11, 0x13];
const ACCENT = [0x7f, 0xd1, 0xae];
const RING_ALPHA = 0.35;
// The favicon's proportions, divided by its 32-unit viewBox: rx 7, dot r 6.5, ring r 11 stroked 1.5.
const CORNER = 7 / 32;
const DOT = 6.5 / 32;
const RING_INNER = 10.25 / 32;
const RING_OUTER = 11.75 / 32;

const CRC_TABLE = Array.from({ length: 256 }, (_, index) => {
  let value = index;
  for (let bit = 0; bit < 8; bit += 1) {
    value = value & 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1;
  }
  return value >>> 0;
});

function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) crc = CRC_TABLE[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

function chunk(type, data) {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length, 0);
  const body = Buffer.concat([Buffer.from(type, "latin1"), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body), 0);
  return Buffer.concat([length, body, crc]);
}

function over(destination, source, alpha) {
  for (let i = 0; i < 3; i += 1) destination[i] = source[i] * alpha + destination[i] * (1 - alpha);
}

function insideRoundedRectangle(x, y) {
  const qx = Math.max(Math.abs(x - 0.5) - (0.5 - CORNER), 0);
  const qy = Math.max(Math.abs(y - 0.5) - (0.5 - CORNER), 0);
  return Math.hypot(qx, qy) <= CORNER;
}

function colourAt(x, y, rounded) {
  if (rounded && !insideRoundedRectangle(x, y)) return [0, 0, 0, 0];
  const pixel = [...INK];
  const distance = Math.hypot(x - 0.5, y - 0.5);
  if (distance >= RING_INNER && distance <= RING_OUTER) over(pixel, ACCENT, RING_ALPHA);
  if (distance <= DOT) over(pixel, ACCENT, 1);
  return [...pixel, 255];
}

/** Four samples per axis: enough that a 192px icon's circle is not visibly stepped. */
function render(size, { rounded }) {
  const scale = 4;
  const total = scale * scale;
  const rgba = Buffer.alloc(size * size * 4);
  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      let r = 0;
      let g = 0;
      let b = 0;
      let covered = 0;
      for (let sy = 0; sy < scale; sy += 1) {
        for (let sx = 0; sx < scale; sx += 1) {
          const [sr, sg, sb, sa] = colourAt((x + (sx + 0.5) / scale) / size, (y + (sy + 0.5) / scale) / size, rounded);
          if (sa === 0) continue;
          r += sr;
          g += sg;
          b += sb;
          covered += 1;
        }
      }
      const index = (y * size + x) * 4;
      if (covered > 0) {
        rgba[index] = Math.round(r / covered);
        rgba[index + 1] = Math.round(g / covered);
        rgba[index + 2] = Math.round(b / covered);
        rgba[index + 3] = Math.round((255 * covered) / total);
      }
    }
  }
  const header = Buffer.alloc(13);
  header.writeUInt32BE(size, 0);
  header.writeUInt32BE(size, 4);
  header[8] = 8; // bit depth
  header[9] = 6; // truecolour with alpha
  const rows = Buffer.alloc(size * (size * 4 + 1));
  for (let y = 0; y < size; y += 1) {
    rows[y * (size * 4 + 1)] = 0; // filter: none
    rgba.copy(rows, y * (size * 4 + 1) + 1, y * size * 4, (y + 1) * size * 4);
  }
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", header),
    chunk("IDAT", deflateSync(rows, { level: 9 })),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

export function writeIcons(directory) {
  mkdirSync(directory, { recursive: true });
  const files = {
    "icon-192.png": render(192, { rounded: true }),
    "icon-512.png": render(512, { rounded: true }),
    // A launcher masks this one to its own shape, so it is a full square with no rounded corners.
    "icon-maskable-512.png": render(512, { rounded: false }),
    "icon-180.png": render(180, { rounded: true }),
  };
  for (const [name, bytes] of Object.entries(files)) writeFileSync(join(directory, name), bytes);
  return Object.keys(files);
}

const here = dirname(fileURLToPath(import.meta.url));
const argument = process.argv.indexOf("--out");
const target = argument === -1 ? join(here, "..", "public", "icons") : resolve(process.argv[argument + 1]);
const written = writeIcons(target);
console.log(`[kira] icons written to ${target}: ${written.join(", ")}`);
