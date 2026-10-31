import { parseDocument } from "yaml";
import { caseFold } from "unicode-case-folding";
import { memoryTagYamlScalars } from "./memoryTagYaml";

export interface FrontmatterEntry {
  key: string;
  value: string;
}

export interface ParsedMarkdownFrontmatter {
  body: string;
  entries: FrontmatterEntry[];
}

const FRONTMATTER_PATTERN = /^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/;
// Python str.split() whitespace, including NEL and U+001C..U+001F.
const TAG_WHITESPACE =
  // eslint-disable-next-line no-control-regex
  /[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+/u;

/** Split a leading YAML frontmatter block from the Markdown body. */
export function parseMarkdownFrontmatter(
  content: string,
): ParsedMarkdownFrontmatter {
  const match = FRONTMATTER_PATTERN.exec(content);
  if (!match) return { body: content, entries: [] };

  const entries: FrontmatterEntry[] = [];
  for (const line of match[1].split(/\r?\n/)) {
    const separator = line.indexOf(":");
    if (separator > 0 && !/^(?:\s|- )/.test(line)) {
      entries.push({
        key: line.slice(0, separator).trim(),
        value: line.slice(separator + 1).trim(),
      });
    } else if (entries.length && line.trim()) {
      const entry = entries[entries.length - 1];
      entry.value = [entry.value, line.trim()].filter(Boolean).join("\n");
    }
  }

  return { body: content.slice(match[0].length), entries };
}

/** Remove YAML frontmatter from the beginning of a Markdown string. */
export const stripFrontmatter = (content: string): string =>
  parseMarkdownFrontmatter(content).body;

/** Read the indexed tag list while retaining the source's display casing. */
export function parseMemoryTags(content: string): string[] {
  const block = FRONTMATTER_PATTERN.exec(content)?.[1];
  if (!block) return [];
  try {
    const document = parseDocument(block, {
      version: "1.1",
      customTags: memoryTagYamlScalars,
      intAsBigInt: true,
      uniqueKeys: false,
    });
    if (document.errors.length) return [];
    const value: unknown = document.toJS({ maxAliasCount: 50 })?.memory_tags;
    if (!Array.isArray(value)) return [];
    const seen = new Set<string>();
    const tags: string[] = [];
    for (const item of value) {
      if (typeof item !== "string" && typeof item !== "bigint") continue;
      const tag = String(item).split(TAG_WHITESPACE).filter(Boolean).join("_");
      if (!tag || [...tag].length > 64 || !/[\p{L}\p{N}]/u.test(tag)) continue;
      const key = caseFold(tag);
      if (seen.has(key)) continue;
      seen.add(key);
      tags.push(tag);
      if (tags.length === 3) break;
    }
    return tags;
  } catch {
    return [];
  }
}
