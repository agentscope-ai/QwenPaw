/** Resolve a Markdown URL against a workspace-relative document path. */
export function resolveMarkdownFilePath(
  filePath: string,
  reference?: string,
): string | null {
  if (!reference || /^(?:[/\\#?]|[a-z][a-z\d+.-]*:)/i.test(reference)) {
    return null;
  }
  let relativePath: string;
  try {
    relativePath = decodeURIComponent(reference.split(/[?#]/, 1)[0]);
  } catch {
    return null;
  }
  const segments = filePath.replace(/\\/g, "/").split("/");
  segments.pop();
  for (const segment of relativePath.replace(/\\/g, "/").split("/")) {
    if (!segment || segment === ".") continue;
    if (segment === "..") {
      if (!segments.length) return null;
      segments.pop();
    } else {
      segments.push(segment);
    }
  }
  return segments.join("/") || null;
}
