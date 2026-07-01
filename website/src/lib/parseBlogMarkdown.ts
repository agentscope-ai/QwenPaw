export interface BlogFrontmatter {
  title: string;
  date: string;
  author?: string;
  tags: string[];
  cover?: string;
  excerpt?: string;
}

export interface ParsedBlogPost {
  frontmatter: BlogFrontmatter;
  body: string;
  readMinutes: number;
  /** Set when the post lists developer-day sessions (`**title**` lines). */
  sessionCount?: number;
}

/** Count session entries formatted as a standalone `**title**` markdown line. */
export function countDeveloperDaySessions(body: string): number {
  return body.split("\n").filter((line) => /^\*\*.+\*\*$/.test(line.trim()))
    .length;
}

function parseYamlValue(raw: string): string | string[] {
  const trimmed = raw.trim();
  if (trimmed.startsWith("[") && trimmed.endsWith("]")) {
    return trimmed
      .slice(1, -1)
      .split(",")
      .map((s) => s.trim().replace(/^["']|["']$/g, ""))
      .filter(Boolean);
  }
  return trimmed.replace(/^["']|["']$/g, "");
}

function parseFrontmatterBlock(block: string): BlogFrontmatter {
  const data: Record<string, string | string[]> = {};
  for (const line of block.split("\n")) {
    const idx = line.indexOf(":");
    if (idx === -1) continue;
    const key = line.slice(0, idx).trim();
    const value = parseYamlValue(line.slice(idx + 1));
    data[key] = value;
  }

  const tags = data.tags;
  return {
    title: String(data.title ?? "Untitled"),
    date: String(data.date ?? ""),
    author: data.author ? String(data.author) : undefined,
    tags: Array.isArray(tags) ? tags : [],
    cover: data.cover ? String(data.cover) : undefined,
    excerpt: data.excerpt ? String(data.excerpt) : undefined,
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

export function parseBlogMarkdown(md: string): ParsedBlogPost {
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

  const frontmatter = parseFrontmatterBlock(match[1]);
  let body = match[2].trim();
  // Drop duplicated H1 when it matches the frontmatter title.
  body = body.replace(/^#\s+.+\n+/, "");
  const sessionCount = countDeveloperDaySessions(body);

  return {
    frontmatter: {
      ...frontmatter,
      excerpt: frontmatter.excerpt ?? extractExcerpt(body),
    },
    body,
    readMinutes: estimateReadMinutes(body),
    ...(sessionCount > 0 ? { sessionCount } : {}),
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
