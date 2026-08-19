import {
  parseInternalFileLink,
  toProjectRelativePath,
} from "../../../../features/files-workspace/internalFileLinks";
import type { FileTarget } from "../../../../features/files-workspace/types";

/** `path:line:> content` / `path:line:  content` (show_file=True). */
const MATCH_WITH_PATH_RE = /^(.*?):(\d+):([> ]) (.*)$/;
/** `line:> content` (show_file=False, after a file header). */
const MATCH_NO_PATH_RE = /^(\d+):([> ]) (.*)$/;

export type GrepResultLine =
  | {
      kind: "match";
      path: string;
      line: number;
      hit: boolean;
      content: string;
      raw: string;
    }
  | {
      kind: "match_no_path";
      path: string | null;
      line: number;
      hit: boolean;
      content: string;
      raw: string;
    }
  | { kind: "file_header"; path: string; raw: string }
  | { kind: "separator"; raw: string }
  | { kind: "text"; raw: string };

export type GrepPathContext = {
  /** Tool param `path` (file or directory search root). */
  searchPath?: string | null;
  /** Active project directory; required to map absolute `searchPath`. */
  projectDirectory?: string | null;
};

function normalizeDisplayPath(rawPath: string): string {
  return rawPath
    .trim()
    .replace(/\\/g, "/")
    .replace(/^(?:\.\/)+/, "")
    .replace(/\/+$/, "");
}

function basename(path: string): string {
  const normalized = normalizeDisplayPath(path);
  const slash = normalized.lastIndexOf("/");
  return slash < 0 ? normalized : normalized.slice(slash + 1);
}

function isAbsoluteFilesystemPath(path: string): boolean {
  const normalized = path.trim().replace(/\\/g, "/");
  return normalized.startsWith("/") || /^[a-z]:\//i.test(normalized);
}

/**
 * Project-relative form of grep's `path` param (backend search_root).
 * - omitted / empty → `undefined` (search defaulted to project/workspace root)
 * - present but not openable (e.g. absolute outside project) → `null`
 */
export function resolveGrepSearchRoot(
  searchPath?: string | null,
  projectDirectory?: string | null,
): string | null | undefined {
  if (searchPath == null || !String(searchPath).trim()) return undefined;
  const normalized = normalizeDisplayPath(String(searchPath));
  if (!normalized) return undefined;
  return toProjectRelativePath(normalized, projectDirectory ?? undefined);
}

/**
 * Map a backend display path onto a project-relative open path.
 *
 * Backend emits basename for single-file searches and paths relative to
 * `search_root` for directory searches — not always project-relative.
 */
export function resolveGrepOpenPath(
  displayPath: string | null | undefined,
  searchRoot: string | null | undefined,
): string | null {
  if (searchRoot === null) return null;
  if (searchRoot === undefined) {
    if (displayPath == null || !String(displayPath).trim()) return null;
    return normalizeDisplayPath(String(displayPath)) || null;
  }

  if (displayPath == null || !String(displayPath).trim()) {
    return searchRoot;
  }

  const display = normalizeDisplayPath(String(displayPath));
  if (!display) return searchRoot;
  if (display === searchRoot) return searchRoot;
  if (display.startsWith(`${searchRoot}/`)) return display;
  // Single-file mode: backend prints only the basename.
  if (display === basename(searchRoot)) return searchRoot;
  return normalizeDisplayPath(`${searchRoot}/${display}`);
}

/** Paths the workspace preview API can open (project-relative, no `..`). */
export function toOpenableFileTarget(
  rawPath: string,
  line?: number,
  pathContext?: GrepPathContext,
): FileTarget | null {
  const searchRoot = pathContext
    ? resolveGrepSearchRoot(
        pathContext.searchPath,
        pathContext.projectDirectory,
      )
    : undefined;
  const path = resolveGrepOpenPath(rawPath, searchRoot);
  if (!path) return null;
  const parsed = parseInternalFileLink(path);
  if (!parsed) return null;
  return {
    ...parsed,
    root: "project",
    line,
    endLine: line,
  };
}

function looksLikeFileHeader(line: string): boolean {
  if (!line || line === "---") return false;
  if (MATCH_WITH_PATH_RE.test(line) || MATCH_NO_PATH_RE.test(line)) {
    return false;
  }
  if (line.startsWith("(") || line.startsWith("No matches")) return false;
  if (/\s/.test(line)) return false;
  // Headers are search-root-relative display paths (may be basename-only).
  const normalized = normalizeDisplayPath(line);
  if (!normalized || isAbsoluteFilesystemPath(normalized)) return false;
  return !normalized.split("/").some((segment) => !segment || segment === "..");
}

/**
 * Rewrite parsed grep paths using tool `path` / project directory so UI
 * clicks open the real project-relative file.
 */
export function remapGrepResultPaths(
  lines: GrepResultLine[],
  pathContext?: GrepPathContext,
): GrepResultLine[] {
  if (!pathContext?.searchPath?.toString().trim()) {
    return lines;
  }

  const searchRoot = resolveGrepSearchRoot(
    pathContext.searchPath,
    pathContext.projectDirectory,
  );

  return lines.map((entry) => {
    if (entry.kind === "match" || entry.kind === "file_header") {
      const path = resolveGrepOpenPath(entry.path, searchRoot);
      if (!path) {
        return { kind: "text", raw: entry.raw };
      }
      return { ...entry, path };
    }
    if (entry.kind === "match_no_path") {
      return {
        ...entry,
        path: resolveGrepOpenPath(entry.path, searchRoot),
      };
    }
    return entry;
  });
}

export function parseGrepResultLines(
  text: string,
  options?: { fallbackPath?: string | null },
): GrepResultLine[] {
  if (!text) return [];

  const lines = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n");
  const parsed: GrepResultLine[] = [];
  const fallback = options?.fallbackPath
    ? normalizeDisplayPath(options.fallbackPath) || null
    : null;
  let currentPath: string | null = fallback;

  for (const raw of lines) {
    if (raw === "---") {
      parsed.push({ kind: "separator", raw });
      continue;
    }

    const withPath = MATCH_WITH_PATH_RE.exec(raw);
    if (withPath) {
      const path = normalizeDisplayPath(withPath[1]);
      const line = Number(withPath[2]);
      // Accept search-root-relative display paths here; remap later.
      if (
        path &&
        Number.isFinite(line) &&
        !isAbsoluteFilesystemPath(path) &&
        !path.split("/").some((segment) => segment === "..")
      ) {
        currentPath = path;
        parsed.push({
          kind: "match",
          path,
          line,
          hit: withPath[3] === ">",
          content: withPath[4],
          raw,
        });
        continue;
      }
    }

    const noPath = MATCH_NO_PATH_RE.exec(raw);
    if (noPath) {
      const line = Number(noPath[1]);
      if (Number.isFinite(line)) {
        parsed.push({
          kind: "match_no_path",
          path: currentPath,
          line,
          hit: noPath[2] === ">",
          content: noPath[3],
          raw,
        });
        continue;
      }
    }

    if (looksLikeFileHeader(raw)) {
      currentPath = normalizeDisplayPath(raw);
      parsed.push({ kind: "file_header", path: currentPath, raw });
      continue;
    }

    parsed.push({ kind: "text", raw });
  }

  return parsed;
}

/** Parse tool output and resolve display paths for opening. */
export function parseGrepResultLinesForOpen(
  text: string,
  pathContext?: GrepPathContext,
): GrepResultLine[] {
  const searchRoot = resolveGrepSearchRoot(
    pathContext?.searchPath,
    pathContext?.projectDirectory,
  );
  const parsed = parseGrepResultLines(text, {
    // Single-file + show_file=False emits only `line:> content`.
    fallbackPath: searchRoot ?? null,
  });
  return remapGrepResultPaths(parsed, pathContext);
}

export function hasOpenableGrepPaths(lines: GrepResultLine[]): boolean {
  return lines.some(
    (line) =>
      (line.kind === "match" && toOpenableFileTarget(line.path) !== null) ||
      (line.kind === "file_header" &&
        toOpenableFileTarget(line.path) !== null) ||
      (line.kind === "match_no_path" &&
        line.path !== null &&
        toOpenableFileTarget(line.path) !== null),
  );
}

/** A single hit line under a file group. */
export interface GrepMatchHit {
  line: number;
  content: string;
}

/** One row per file for the Cursor-style result list. */
export interface GrepFileHit {
  path: string;
  /** First hit line (preferred) or first context/header line. */
  line?: number;
  hitCount: number;
  /** Hit rows only (excludes context lines), in appearance order. */
  matches: GrepMatchHit[];
}

function splitDisplayPath(path: string): { name: string; directory: string } {
  const normalized = normalizeDisplayPath(path);
  const slash = normalized.lastIndexOf("/");
  if (slash < 0) return { name: normalized, directory: "" };
  return {
    name: normalized.slice(slash + 1) || normalized,
    directory: normalized.slice(0, slash),
  };
}

export function displayPartsForGrepPath(path: string): {
  name: string;
  directory: string;
} {
  return splitDisplayPath(path);
}

function appendHit(
  hit: GrepFileHit,
  line: number,
  content: string,
  isHit: boolean,
): void {
  if (isHit) {
    hit.hitCount += 1;
    hit.matches.push({ line, content });
    if (hit.line === undefined) hit.line = line;
    return;
  }
  if (hit.line === undefined) hit.line = line;
}

/**
 * Collapse parsed grep lines into one clickable file entry each.
 * Prefers the first hit line for navigation; keeps all hit rows for expand.
 */
export function groupGrepFileHits(lines: GrepResultLine[]): GrepFileHit[] {
  const order: string[] = [];
  const byPath = new Map<string, GrepFileHit>();

  const ensure = (path: string): GrepFileHit => {
    let hit = byPath.get(path);
    if (!hit) {
      hit = { path, hitCount: 0, matches: [] };
      byPath.set(path, hit);
      order.push(path);
    }
    return hit;
  };

  for (const entry of lines) {
    if (entry.kind === "match") {
      appendHit(ensure(entry.path), entry.line, entry.content, entry.hit);
      continue;
    }
    if (entry.kind === "match_no_path" && entry.path) {
      appendHit(ensure(entry.path), entry.line, entry.content, entry.hit);
      continue;
    }
    if (entry.kind === "file_header") {
      ensure(entry.path);
    }
  }

  return order.map((path) => byPath.get(path)!);
}

export function dispatchOpenFilePreview(
  target: FileTarget,
  trigger: HTMLElement | null,
  options?: { workspace?: boolean },
): void {
  window.dispatchEvent(
    new CustomEvent("qwenpaw:open-file-preview", {
      detail: {
        target,
        trigger,
        // Prefer the coding workspace editor so line navigation / highlight works.
        workspace: options?.workspace ?? false,
      },
    }),
  );
}
