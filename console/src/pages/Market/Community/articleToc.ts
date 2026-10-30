import DOMPurify from "dompurify";

export interface TocItem {
  id: string;
  text: string;
  level: number;
}

/** Same options as the article body sanitizer so heading order stays aligned. */
export function sanitizeArticleHtml(html: string): string {
  if (!html?.trim()) return "";
  return DOMPurify.sanitize(html, {
    USE_PROFILES: { html: true },
    FORBID_TAGS: ["style", "form", "input", "button", "iframe", "audio"],
    FORBID_ATTR: ["style", "id", "name", "srcset", "autoplay", "loop"],
  });
}

function slugifyHeading(text: string, index: number): string {
  const base = text
    .toLowerCase()
    .trim()
    .replace(/\s+/g, "-")
    .replace(/[^\w一-鿿-]/g, "")
    .slice(0, 48);
  return base || `heading-${index + 1}`;
}

/** Assign stable ids to headings in place; mirrors extractHtmlToc ordering. */
export function assignHeadingIds(root: HTMLElement): void {
  const used = new Set<string>();
  root.querySelectorAll("h1, h2, h3, h4, h5, h6").forEach((el, index) => {
    const text = (el.textContent || "").replace(/\s+/g, " ").trim();
    const preferred = slugifyHeading(text, index);
    let id = preferred;
    let suffix = 1;
    while (used.has(id)) {
      id = `${preferred}-${suffix}`;
      suffix += 1;
    }
    used.add(id);
    el.id = id;
  });
}

/** Extract toc items from article HTML using the same ids the body gets. */
export function extractHtmlToc(html: string): TocItem[] {
  const sanitized = sanitizeArticleHtml(html);
  if (!sanitized.trim() || typeof DOMParser === "undefined") return [];
  const doc = new DOMParser().parseFromString(sanitized, "text/html");
  const toc: TocItem[] = [];
  const used = new Set<string>();
  doc.body.querySelectorAll("h1, h2, h3, h4, h5, h6").forEach((el, index) => {
    const text = (el.textContent || "").replace(/\s+/g, " ").trim();
    if (!text) return;
    const preferred = slugifyHeading(text, index);
    let id = preferred;
    let suffix = 1;
    while (used.has(id)) {
      id = `${preferred}-${suffix}`;
      suffix += 1;
    }
    used.add(id);
    toc.push({ id, text, level: Number(el.tagName.slice(1)) });
  });
  return toc;
}

/**
 * Extract toc from markdown source; ids follow heading occurrence order
 * (md-heading-N) exactly like the renderer-side counter, empty headings
 * included so numbering stays aligned. Fences are skipped.
 */
export function parseMarkdownToc(markdown: string): TocItem[] {
  const toc: TocItem[] = [];
  const lines = markdown.split(/\r?\n/);
  let inFence = false;
  let index = 0;
  let prevText = "";
  let prevIsParagraph = false;

  const cleanInline = (s: string) =>
    s
      .replace(/`([^`]*)`/g, "$1")
      .replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1")
      .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
      .replace(/[*_~]+/g, "")
      .replace(/\s+/g, " ")
      .trim();

  const take = (text: string, level: number) => {
    if (text) toc.push({ id: `md-heading-${index}`, text, level });
    index += 1;
  };

  for (const rawLine of lines) {
    const raw = rawLine.trimEnd();
    if (/^\s{0,3}(```|~~~)/.test(raw)) {
      inFence = !inFence;
      prevIsParagraph = false;
      prevText = "";
      continue;
    }
    if (inFence) continue;
    if (prevIsParagraph && /^\s{0,3}(=+|-+)\s*$/.test(raw)) {
      take(cleanInline(prevText), raw.trim().startsWith("=") ? 1 : 2);
      prevIsParagraph = false;
      prevText = "";
      continue;
    }
    const content = raw
      .replace(/^\s{0,3}(>\s?)+/, "")
      .replace(/^\s{0,3}([-*+]|\d{1,9}[.)])\s+/, "")
      .trim();
    if (!content) {
      prevIsParagraph = false;
      prevText = "";
      continue;
    }
    const atx = content.match(/^(#{1,6})(?:\s+(.*?))?(?:\s+#+)?\s*$/);
    if (atx && /^(#{1,6})(\s|$)/.test(content)) {
      take(cleanInline(atx[2] || ""), atx[1].length);
      prevIsParagraph = false;
      prevText = "";
      continue;
    }
    if (/^\s{0,3}(?:(?:-\s*){3,}|(?:\*\s*){3,}|(?:_\s*){3,})$/.test(content)) {
      prevIsParagraph = false;
      prevText = "";
      continue;
    }
    prevIsParagraph = true;
    prevText = content;
  }
  return toc;
}
