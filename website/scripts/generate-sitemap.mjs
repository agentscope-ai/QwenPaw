#!/usr/bin/env node
/**
 * Generate sitemap.xml from the same DOC_GROUPS source used by the docs UI.
 * Run before vite build so dist gets an up-to-date sitemap.
 */
import { readFile, writeFile } from "fs/promises";
import { join } from "path";
import { fileURLToPath } from "url";

const __dirname = fileURLToPath(new URL(".", import.meta.url));
const navigationPath = join(
  __dirname,
  "..",
  "src",
  "pages",
  "Docs",
  "navigation.ts",
);
const outPath = join(__dirname, "..", "public", "sitemap.xml");

const SITE_URL = "https://qwenpaw.agentscope.io";

// Pages outside the docs section.
const STATIC_PAGES = [
  { path: "/", priority: "1.0" },
  { path: "/downloads/", priority: "1.0" },
  { path: "/release-notes/", priority: "0.9" },
];

// Override defaults for specific doc slugs.
const PRIORITY_OVERRIDES = {
  intro: "0.9",
  quickstart: "0.9",
  config: "0.7",
  backup: "0.7",
  cli: "0.7",
  plugins: "0.7",
  "practice-agent-team": "0.7",
  faq: "0.7",
  "api-tutorial": "0.7",
  "acp-integration": "0.7",
  community: "0.7",
  contributing: "0.7",
  roadmap: "0.7",
  comparison: "0.7",
  search: "0.6",
};

const DEFAULT_DOC_PRIORITY = "0.8";

function escapeXml(str) {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

async function extractDocSlugs() {
  const source = await readFile(navigationPath, "utf-8");
  const slugs = [];
  // Match every `slug: "..."` occurrence inside DOC_GROUPS.
  const slugRegex = /slug:\s*"([^"]+)"/g;
  let match;
  while ((match = slugRegex.exec(source)) !== null) {
    slugs.push(match[1]);
  }
  if (slugs.length === 0) {
    throw new Error(`No doc slugs found in ${navigationPath}`);
  }

  // ALL_SLUGS also contains "comparison" which is hidden from DOC_GROUPS nav.
  if (!slugs.includes("comparison")) {
    slugs.push("comparison");
  }

  // The search page is a special docs route, not in DOC_GROUPS.
  if (!slugs.includes("search")) {
    slugs.push("search");
  }

  return [...new Set(slugs)].sort();
}

function buildUrlElement(path, priority) {
  const loc = `${SITE_URL}${escapeXml(path)}`;
  const today = new Date().toISOString().split("T")[0];
  return `  <url>\n    <loc>${loc}</loc>\n    <lastmod>${today}</lastmod>\n    <priority>${priority}</priority>\n  </url>`;
}

async function main() {
  const docSlugs = await extractDocSlugs();

  const urlElements = [
    ...STATIC_PAGES.map((p) => buildUrlElement(p.path, p.priority)),
    ...docSlugs.map((slug) => {
      const priority = PRIORITY_OVERRIDES[slug] ?? DEFAULT_DOC_PRIORITY;
      return buildUrlElement(`/docs/${slug}/`, priority);
    }),
  ];

  const sitemap = `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urlElements.join(
    "\n",
  )}\n</urlset>\n`;

  await writeFile(outPath, sitemap, "utf-8");
  console.log(
    `Wrote sitemap.xml with ${urlElements.length} URLs to ${outPath}`,
  );
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
