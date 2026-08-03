#!/usr/bin/env node
/**
 * Build guard: assert the console bundle still ships Monaco's stylesheet.
 *
 * Monaco keeps a hidden `<textarea class="inputarea">` for keyboard / IME
 * input. Without `monaco-editor`'s CSS that textarea renders with browser
 * default styles (a large white box floating over the code) and the editor
 * loses its input-layer positioning, so clicks no longer land on the caret
 * (issue #6547). That is exactly what happens when node_modules CSS is
 * stubbed out during a real build, so fail loudly instead of shipping a
 * broken Coding Mode editor.
 *
 * Usage: node scripts/verify-monaco-css.mjs [outDir]   (default: dist)
 */
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";

// Substrings that only exist in monaco-editor's stylesheet. Deliberately not
// tied to hashed file names or minified whitespace.
const MARKERS = ["inputarea", "overflow-guard"];

function collectCssFiles(dir) {
  const found = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      found.push(...collectCssFiles(full));
    } else if (entry.name.endsWith(".css")) {
      found.push(full);
    }
  }
  return found;
}

const outDir = process.argv[2] ?? "dist";
let cssFiles;
try {
  cssFiles = collectCssFiles(outDir);
} catch (err) {
  console.error(`[verify-monaco-css] cannot read build output "${outDir}"`);
  throw err;
}

const missing = MARKERS.filter(
  (marker) =>
    !cssFiles.some((file) => readFileSync(file, "utf8").includes(marker)),
);

if (cssFiles.length === 0 || missing.length > 0) {
  console.error(
    `[verify-monaco-css] Monaco stylesheet missing from ${outDir}: ` +
      `${missing.join(", ") || "no CSS emitted at all"}.\n` +
      "The Coding Mode editor will show a floating white textarea and " +
      "misplaced cursor. Check that no plugin stubs node_modules CSS " +
      "during builds (console/vite.config.ts).",
  );
  process.exit(1);
}

console.log(
  `[verify-monaco-css] OK - Monaco stylesheet present in ${cssFiles.length} CSS file(s).`,
);
