/** Extract `path` query from artifact preview/download URLs. */
function extractPathFromArtifactFileUrl(url?: string | null): string | null {
  if (!url) return null;
  const trimmed = url.trim();
  if (!trimmed) return null;

  try {
    const parsed = trimmed.startsWith("http")
      ? new URL(trimmed)
      : new URL(trimmed, "http://localhost");
    const fromQuery = parsed.searchParams.get("path");
    if (fromQuery) return decodeURIComponent(fromQuery);
  } catch {
    /* fall through to regex */
  }

  const match = trimmed.match(/[?&]path=([^&#]+)/);
  if (!match?.[1]) return null;
  try {
    return decodeURIComponent(match[1]);
  } catch {
    return match[1];
  }
}

function stripArtifactPathPrefixes(path: string): string {
  let normalized = path.trim().replace(/\\/g, "/").replace(/^\/+/, "");
  if (normalized.startsWith("workspace/artifacts/")) {
    normalized = normalized.slice("workspace/artifacts/".length);
  } else if (normalized.startsWith("artifacts/")) {
    normalized = normalized.slice("artifacts/".length);
  }
  return normalized;
}

/**
 * Normalize artifact paths for `/api/tasks/{sid}/files/{preview|download}`.
 * Registry paths omit the `artifacts/` prefix; some UI sources still include it.
 */
export function normalizeArtifactApiPath(
  ...candidates: (string | null | undefined)[]
): string {
  for (const candidate of candidates) {
    if (!candidate) continue;

    const extracted = extractPathFromArtifactFileUrl(candidate);
    const raw = extracted ?? candidate;
    const normalized = stripArtifactPathPrefixes(raw);
    if (normalized) return normalized;
  }
  return "";
}

export function normalizeArtifactFileRecord<
  T extends {
    path?: string;
    preview_url?: string;
    download_url?: string;
  },
>(file: T): T {
  const path = normalizeArtifactApiPath(
    file.path,
    file.preview_url,
    file.download_url,
  );
  if (!path || path === file.path) return file;
  return { ...file, path };
}
