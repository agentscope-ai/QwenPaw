// Vite preserves the source HTML filename for multi-page builds. Tauri expects
// the bundled frontend directory to contain index.html, so rename the small
// desktop bootstrap page after the Vite build.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, "../..");
const distDir = path.join(repoRoot, "console", "dist-tauri");
const source = path.join(distDir, "tauri.html");
const target = path.join(distDir, "index.html");

if (!fs.existsSync(source)) {
  throw new Error(`Tauri bootstrap HTML not found: ${source}`);
}

if (fs.existsSync(target)) {
  fs.rmSync(target);
}

fs.renameSync(source, target);
console.log(`Wrote Tauri bootstrap ${target}`);
