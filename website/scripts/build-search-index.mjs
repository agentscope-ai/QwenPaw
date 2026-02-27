#!/usr/bin/env node
/**
 * Build search-index.json from docs/*.zh.md and *.en.md for client-side search.
 * Run before vite build so dist gets the index.
 */
import { readdir, readFile, writeFile } from "fs/promises";
import { join } from "path";
import { fileURLToPath } from "url";

const __dirname = fileURLToPath(new URL(".", import.meta.url));
const docsDir = join(__dirname, "..", "public", "docs");
const outPath = join(__dirname, "..", "public", "search-index.json");

const EXCERPT_LEN = 800;

function slugifyHeading(text) {
  const s = text
    .trim()
    .replace(/\s+/g, "-")
    .replace(/[^a-zA-Z0-9_\-\u4e00-\u9fa5]/g, "");
  return s || "section";
}

function stripMarkdownForExcerpt(md) {
  return md
    .replace(/^#+\s+.+$/gm, "")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/[*_`#]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function parseDoc(md) {
  const lines = md.split("\n");
  let title = "";
  const headings = [];
  let body = [];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const h2 = /^##\s+(.+)$/.exec(line);
    const h3 = /^###\s+(.+)$/.exec(line);
    if (i === 0 && line.startsWith("# ")) {
      title = line
        .slice(2)
        .replace(/#+\s*$/, "")
        .trim();
      continue;
    }
    if (h2) {
      const text = h2[1].replace(/#+\s*$/, "").trim();
      headings.push({ level: 2, text, id: slugifyHeading(text) });
      continue;
    }
    if (h3) {
      const text = h3[1].replace(/#+\s*$/, "").trim();
      headings.push({ level: 3, text, id: slugifyHeading(text) });
      continue;
    }
    if (!title && line.trim()) title = line.replace(/#+\s*$/, "").trim();
    body.push(line);
  }

  const fullBody = body.join("\n");
  const excerpt = stripMarkdownForExcerpt(fullBody).slice(0, EXCERPT_LEN);

  return { title: title || "Untitled", headings, excerpt };
}

async function main() {
  const files = await readdir(docsDir);
  const entries = [];

  for (const f of files) {
    const zhMatch = f.match(/^(.+)\.zh\.md$/);
    const enMatch = f.match(/^(.+)\.en\.md$/);
    const lang = zhMatch ? "zh" : enMatch ? "en" : null;
    const slug = zhMatch?.[1] ?? enMatch?.[1];
    if (!lang || !slug) continue;

    const path = join(docsDir, f);
    const md = await readFile(path, "utf-8");
    const { title, headings, excerpt } = parseDoc(md);
    entries.push({
      slug,
      lang,
      title,
      headings: headings.map((h) => ({ text: h.text, id: h.id })),
      excerpt,
    });
  }

  await writeFile(outPath, JSON.stringify(entries), "utf-8");
  console.log(`Wrote ${entries.length} doc entries to ${outPath}`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
