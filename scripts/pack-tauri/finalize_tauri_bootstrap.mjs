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

// Copy control-overlay.html into dist-tauri for the control mode overlay window
const overlaySource = path.join(repoRoot, "console", "src-tauri", "static", "control-overlay.html");
const overlayTarget = path.join(distDir, "control-overlay.html");
if (fs.existsSync(overlaySource)) {
  fs.copyFileSync(overlaySource, overlayTarget);
  console.log(`Copied control overlay ${overlayTarget}`);
}

// Copy control-overlay.js
const overlayJsSource = path.join(repoRoot, "console", "src-tauri", "static", "control-overlay.js");
const overlayJsTarget = path.join(distDir, "control-overlay.js");
if (fs.existsSync(overlayJsSource)) {
  fs.copyFileSync(overlayJsSource, overlayJsTarget);
  console.log(`Copied control overlay JS ${overlayJsTarget}`);
}
