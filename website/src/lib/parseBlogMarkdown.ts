import yaml from "js-yaml";

export interface BlogRelatedItem {
  label: string;
  name: string;
  href?: string;
  description?: string;
}

export interface BlogRelatedMeta {
  heading: string;
  description?: string;
  linkText?: string;
  linkUrl?: string;
  items?: BlogRelatedItem[];
}

export interface BlogFrontmatter {
  title: string;
  date: string;
  author?: string;
  tags: string[];
  cover?: string;
  excerpt?: string;
  related?: BlogRelatedMeta;
}

export interface ParsedBlogPost {
  frontmatter: BlogFrontmatter;
  body: string;
  readMinutes: number;
  /** Set when the post lists developer-day sessions. */
  sessionCount?: number;
}

export type ParseBlogMarkdownOptions = {
  /** When true, count developer-day session titles in the body. */
  sessionList?: boolean;
};

/** Newest first; empty dates sink to the bottom; slug breaks ties. */
export function compareBlogPostsByDateDesc(
  a: { slug: string; frontmatter: { date: string } },
  b: { slug: string; frontmatter: { date: string } },
): number {
  const dateA = a.frontmatter.date;
  const dateB = b.frontmatter.date;
  if (!dateA && !dateB) return a.slug.localeCompare(b.slug);
  if (!dateA) return 1;
  if (!dateB) return -1;
  if (dateA !== dateB) return dateB.localeCompare(dateA);
  return a.slug.localeCompare(b.slug);
}

/** Match session titles like `**06-30 QwenPaw 开发者日会：…**`. */
const SESSION_TITLE_LINE =
  /^\*\*\d{2}-\d{2}\s+.*(?:开发者日会|Developer Day).*\*\*$/;

export function countDeveloperDaySessions(body: string): number {
  return body.split("\n").filter((line) => SESSION_TITLE_LINE.test(line.trim()))
    .length;
}

function normalizeTags(raw: unknown): string[] {
  if (Array.isArray(raw)) {
    return raw.map(String).filter(Boolean);
  }
  if (typeof raw === "string" && raw.trim()) {
    return [raw.trim()];
  }
  return [];
}

function formatFrontmatterValue(value: unknown): string {
  if (value instanceof Date) {
    return value.toISOString().slice(0, 10);
  }
  return String(value);
}

function normalizeRelated(raw: unknown): BlogRelatedMeta | undefined {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return undefined;
  const data = raw as Record<string, unknown>;
  const heading = data.heading != null ? String(data.heading).trim() : "";
  if (!heading) return undefined;

  const itemsRaw = data.items;
  const items: BlogRelatedItem[] = [];
  if (Array.isArray(itemsRaw)) {
    for (const entry of itemsRaw) {
      if (!entry || typeof entry !== "object" || Array.isArray(entry)) continue;
      const item = entry as Record<string, unknown>;
      const label = item.label != null ? String(item.label).trim() : "";
      const name = item.name != null ? String(item.name).trim() : "";
      if (!label || !name) continue;
      items.push({
        label,
        name,
        href: item.href != null ? String(item.href) : undefined,
        description:
          item.description != null ? String(item.description) : undefined,
      });
    }
  }

  return {
    heading,
    description:
      data.description != null ? String(data.description) : undefined,
    linkText: data.linkText != null ? String(data.linkText) : undefined,
    linkUrl: data.linkUrl != null ? String(data.linkUrl) : undefined,
    ...(items.length > 0 ? { items } : {}),
  };
}

function normalizeFrontmatter(data: Record<string, unknown>): BlogFrontmatter {
  return {
    title: String(data.title ?? "Untitled"),
    date: data.date != null ? formatFrontmatterValue(data.date) : "",
    author: data.author != null ? String(data.author) : undefined,
    tags: normalizeTags(data.tags),
    cover: data.cover != null ? String(data.cover) : undefined,
    excerpt: data.excerpt != null ? String(data.excerpt) : undefined,
    related: normalizeRelated(data.related),
  };
}

function stripMarkdown(text: string): string {
  return text
    .replace(/^#+\s+/gm, "")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/[*_`>#-]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function estimateReadMinutes(body: string): number {
  const plain = stripMarkdown(body);
  if (!plain) return 1;
  const cjk = (plain.match(/[\u4e00-\u9fff]/g) ?? []).length;
  const latin = plain.length - cjk;
  const minutes = Math.ceil(cjk / 400 + latin / 900);
  return Math.max(1, minutes);
}

function extractExcerpt(body: string): string {
  const paragraphs = body
    .split(/\n{2,}/)
    .map((p) => stripMarkdown(p))
    .filter((p) => p.length > 40);
  return paragraphs[0] ?? stripMarkdown(body);
}

export function parseBlogMarkdown(
  md: string,
  options: ParseBlogMarkdownOptions = {},
): ParsedBlogPost {
  const match = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/.exec(md);
  if (!match) {
    const body = md.trim();
    return {
      frontmatter: {
        title: "Untitled",
        date: "",
        tags: [],
      },
      body,
      readMinutes: estimateReadMinutes(body),
    };
  }

  let data: Record<string, unknown> = {};
  try {
    const parsed = yaml.load(match[1]);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      data = parsed as Record<string, unknown>;
    }
  } catch {
    data = {};
  }

  const frontmatter = normalizeFrontmatter(data);
  let body = match[2].trim();
  body = body.replace(/^#\s+.+\n+/, "");

  const sessionCount = options.sessionList
    ? countDeveloperDaySessions(body)
    : undefined;

  return {
    frontmatter: {
      ...frontmatter,
      excerpt: frontmatter.excerpt ?? extractExcerpt(body),
    },
    body,
    readMinutes: estimateReadMinutes(body),
    ...(sessionCount != null && sessionCount > 0 ? { sessionCount } : {}),
  };
}

export function formatBlogDate(date: string, locale: string): string {
  if (!date) return "";
  const parsed = new Date(date);
  if (Number.isNaN(parsed.getTime())) return date;
  return new Intl.DateTimeFormat(locale.startsWith("zh") ? "zh-CN" : "en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
  }).format(parsed);
}
