export function parseFrontmatter(
  content: string,
): Record<string, string> | null {
  try {
    const trimmed = content.trim();
    if (!trimmed.startsWith("---")) return null;
    const endIndex = trimmed.indexOf("---", 3);
    if (endIndex === -1) return null;
    const frontmatterBlock = trimmed.slice(3, endIndex).trim();
    if (!frontmatterBlock) return null;
    const result: Record<string, string> = {};
    for (const line of frontmatterBlock.split("\n")) {
      const colonIndex = line.indexOf(":");
      if (colonIndex > 0) {
        const key = line.slice(0, colonIndex).trim();
        const value = line.slice(colonIndex + 1).trim();
        result[key] = value;
      }
    }
    return result;
  } catch {
    return null;
  }
}
