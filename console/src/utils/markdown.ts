export interface FrontmatterEntry {
  key: string;
  value: string;
}

export interface ParsedMarkdownFrontmatter {
  body: string;
  entries: FrontmatterEntry[];
}

const FRONTMATTER_PATTERN = /^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/;

/** Split a leading YAML frontmatter block from the Markdown body. */
export function parseMarkdownFrontmatter(
  content: string,
): ParsedMarkdownFrontmatter {
  const match = FRONTMATTER_PATTERN.exec(content);
  if (!match) return { body: content, entries: [] };

  const entries = match[1]
    .split(/\r?\n/)
    .map((line) => {
      const separator = line.indexOf(":");
      if (separator <= 0 || /^\s/.test(line)) return null;

      return {
        key: line.slice(0, separator).trim(),
        value: line.slice(separator + 1).trim(),
      };
    })
    .filter((entry): entry is FrontmatterEntry => entry !== null);

  return { body: content.slice(match[0].length), entries };
}

/** Remove YAML frontmatter from the beginning of a Markdown string. */
export const stripFrontmatter = (content: string): string =>
  parseMarkdownFrontmatter(content).body;
