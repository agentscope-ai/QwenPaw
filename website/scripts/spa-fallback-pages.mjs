#!/usr/bin/env node
/**
 * After vite build, copy index.html into docs/ and docs/<slug>/ so that
 * static hosts (e.g. GitHub Pages) serve the SPA for each route without
 * needing a Node server. Must match DOC_SLUGS in src/pages/Docs.tsx.
 */
import { mkdir, readFile, writeFile } from "fs/promises";
import { dirname, join } from "path";
import { fileURLToPath } from "url";

const __dirname = fileURLToPath(new URL(".", import.meta.url));
const distDir = join(__dirname, "..", "dist");

const DOC_SLUGS = [
  "intro",
  "quickstart",
  "console",
  "channels",
  "skills",
  "memory",
  "compact",
  "commands",
  "heartbeat",
  "config",
  "cli",
  "community",
  "contributing",
];

async function main() {
  const indexHtml = await readFile(join(distDir, "index.html"), "utf-8");
  const paths = ["docs", "docs/search", ...DOC_SLUGS.map((s) => `docs/${s}`)];
  for (const p of paths) {
    const out = join(distDir, p, "index.html");
    await mkdir(dirname(out), { recursive: true });
    await writeFile(out, indexHtml);
  }
  console.log("[spa-fallback-pages] Wrote index.html for /, /docs, /docs/*");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
