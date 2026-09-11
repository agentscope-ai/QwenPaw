import type { FileTarget } from "./types";

const EXTERNAL_SCHEMES = new Set(["http:", "https:", "mailto:"]);

function hasUnsafeSegment(path: string): boolean {
  return path
    .split("/")
    .some((segment) => !segment || segment === "." || segment === "..");
}

export function parseInternalFileLink(rawHref: string): FileTarget | null {
  const href = rawHref.trim();
  if (!href || href.startsWith("/") || href.startsWith("\\")) {
    return null;
  }
  const scheme = /^[a-z][a-z\d+.-]*:/i.exec(href)?.[0].toLowerCase();
  if (scheme) {
    return EXTERNAL_SCHEMES.has(scheme) ? null : null;
  }

  const [rawPath, fragment = ""] = href.split("#", 2);
  let path: string;
  try {
    path = decodeURIComponent(rawPath);
  } catch {
    return null;
  }
  if (
    !path ||
    path.includes("\\") ||
    /^[a-z]:/i.test(path) ||
    hasUnsafeSegment(path)
  ) {
    return null;
  }

  const lineMatch = /^L(\d+)(?:C(\d+))?$/.exec(fragment);
  if (fragment && !lineMatch) return null;
  return {
    source: "workspace",
    path,
    line: lineMatch ? Number(lineMatch[1]) : undefined,
    column: lineMatch?.[2] ? Number(lineMatch[2]) : undefined,
  };
}

export function toProjectRelativePath(
  rawPath: string,
  projectDirectory?: string,
): string | null {
  const path = rawPath.trim().replace(/\\/g, "/");
  const direct = parseInternalFileLink(path);
  if (direct) return direct.path;
  if (!projectDirectory) return null;

  const root = projectDirectory.trim().replace(/\\/g, "/").replace(/\/+$/, "");
  const ignoreCase = /^[a-z]:\//i.test(root);
  const comparablePath = ignoreCase ? path.toLowerCase() : path;
  const comparableRoot = ignoreCase ? root.toLowerCase() : root;
  if (!comparablePath.startsWith(`${comparableRoot}/`)) return null;
  return parseInternalFileLink(path.slice(root.length + 1))?.path ?? null;
}

function normalizeComparablePath(path: string): string {
  const normalized = path.trim().replace(/\\/g, "/").replace(/\/+$/, "");
  return /^[a-z]:\//i.test(normalized) ? normalized.toLowerCase() : normalized;
}

function isWithinDirectory(path: string, directory: string): boolean {
  const candidate = normalizeComparablePath(path);
  const root = normalizeComparablePath(directory);
  return candidate === root || candidate.startsWith(`${root}/`);
}

export function rootForFileReference(
  path: string,
  projectDirectory: string,
  workspaceDirectory: string,
): "project" | "workspace" {
  const normalized = path.trim().replace(/\\/g, "/");
  const absolute = normalized.startsWith("/") || /^[a-z]:\//i.test(normalized);
  if (!absolute || isWithinDirectory(normalized, projectDirectory)) {
    return "project";
  }
  return isWithinDirectory(normalized, workspaceDirectory)
    ? "workspace"
    : "project";
}

export function filePathFromPreviewUrl(rawUrl: string): string | null {
  const marker = "/files/preview/";
  const markerIndex = rawUrl.indexOf(marker);
  if (markerIndex < 0) return null;
  const encodedPath = rawUrl
    .slice(markerIndex + marker.length)
    .split(/[?#]/, 1)[0];
  if (!encodedPath) return null;
  try {
    const decoded = decodeURIComponent(encodedPath).replace(/\\/g, "/");
    if (/^[a-z]:\//i.test(decoded)) return decoded;
    return `/${decoded.replace(/^\/+/, "")}`;
  } catch {
    return null;
  }
}
