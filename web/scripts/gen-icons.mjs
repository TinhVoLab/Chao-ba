// Generates PWA icons (SVG source of truth + PNG renders via sharp). Run: node scripts/gen-icons.mjs
import { writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import sharp from "sharp";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const icon = (pad) => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <rect width="512" height="512" rx="${pad ? 0 : 112}" fill="#2f3a7a"/>
  <g transform="translate(256 248) scale(${pad ? 0.72 : 1})">
    <path d="M-150 -120 h300 a46 46 0 0 1 46 46 v148 a46 46 0 0 1 -46 46 h-150 l-74 62 v-62 h-76 a46 46 0 0 1 -46 -46 v-148 a46 46 0 0 1 46 -46z" fill="#f7f1e6"/>
    <circle cx="-86" cy="0" r="36" fill="#2e8b57"/>
    <path d="M0 -36 L38 30 H-38 Z" fill="#e0a526" stroke="#e0a526" stroke-width="10" stroke-linejoin="round"/>
    <path d="M71 -26 l15 -15 h30 l15 15 v30 l-15 15 h-30 l-15 -15z" transform="translate(0 4) scale(1.15) translate(-14 0)" fill="#c8402f"/>
  </g>
</svg>`;
writeFileSync(join(root, "public/icons/icon.svg"), icon(false));
writeFileSync(join(root, "public/icons/icon-maskable.svg"), icon(true));
writeFileSync(join(root, "app/icon.svg"), icon(false));
for (const [name, size, pad] of [["icon-192.png", 192, false], ["icon-512.png", 512, false], ["icon-maskable-512.png", 512, true]]) {
  await sharp(Buffer.from(icon(pad))).resize(size, size).png().toFile(join(root, "public/icons", name));
}
await sharp(Buffer.from(icon(false))).resize(180, 180).png().toFile(join(root, "app/apple-icon.png"));
console.log("icons written");
