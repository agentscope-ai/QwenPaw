/**
 * Local file-path detection and explorer-opening utilities.
 *
 * Detects absolute local paths (Windows, Unix, ~/…) in plain text so the
 * chat UI can render them as clickable links that open the system file
 * explorer via the Tauri `open_in_explorer` command.
 */
import { invoke } from "@tauri-apps/api/core";
import { isDesktopApp } from "../tauri/backendRuntime";
import { getPyWebViewApi } from "./pywebview";

// ---------------------------------------------------------------------------
// Path detection regex
// ---------------------------------------------------------------------------

/**
 * Matches a Windows drive path: `C:\…` or `C:/…`.
 * The drive letter is case-insensitive.  We require at least one segment
 * after the drive root to avoid matching stray single letters.
 */
const WINDOWS_DRIVE_RE = /\b[A-Za-z]:[\\/][^\s<>:"|?*\x00-\x1f]{1,200}/g;

/**
 * Characters that terminate a path segment.  Includes whitespace, the path
 * separator itself, ASCII punctuation that is unlikely in real paths, and
 * common CJK punctuation so that prose like `IMAP/SMTP` or `CI/CD` is not
 * swallowed into a bogus path match.
 */
const PATH_SEGMENT_CHARS =
  "[^\\s/<>|&;,'\"`$(){}!，、。：；？！（）【】《》「」『』“”‘’—…\\x00-\\x1f]{1,200}";

/**
 * Common Unix root directories.  A single-segment absolute path such as `/tmp`
 * or `/home` is accepted only when it is one of these known roots; otherwise
 * we require at least two segments (`/a/b`).  This prevents `/SMTP` in
 * `IMAP/SMTP` from being treated as a path.
 */
const KNOWN_UNIX_ROOTS =
  "(?:usr|bin|etc|var|opt|tmp|home|Users|root|lib|srv|mnt|media|dev|proc|sys|run|boot)";

/**
 * Matches a Unix absolute path starting with `/`.
 *
 * - The leading `/` must not be preceded by `:` (URLs like `http://...`) or
 *   by a word character (prose separators like `IMAP/SMTP`).
 * - The path must either have at least two segments or start with a known
 *   root directory (`/tmp`, `/home`, `/Users`, ...).
 * - CJK punctuation is treated as a segment terminator.
 */
const UNIX_ABSOLUTE_RE = new RegExp(
  `(?<![:/\\\\w])\\/(?:(?:${PATH_SEGMENT_CHARS}\\/){1,10}${PATH_SEGMENT_CHARS}|${KNOWN_UNIX_ROOTS}(?:\\/${PATH_SEGMENT_CHARS})?)`,
  "g",
);

/**
 * Matches a home-directory shorthand: `~/…`.
 */
const HOME_TILDE_RE = /~\/[^\s<>|&;'"`$(){}!\x00-\x1f]{1,200}/g;

/** Trailing punctuation that is almost certainly NOT part of the path. */
const TRAILING_PUNCT_RE = /[.,;:!?)]+$/;

/**
 * Combined regex that matches any of the three path styles.
 * Built once and reused; `lastIndex` is reset before every use because the
 * component regexes carry the `g` flag.
 */
const LOCAL_PATH_RE = new RegExp(
  `(?:${WINDOWS_DRIVE_RE.source})|(?:${UNIX_ABSOLUTE_RE.source})|(?:${HOME_TILDE_RE.source})`,
  "g",
);

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export interface LocalPathMatch {
  /** The detected path string (trimmed of trailing punctuation). */
  path: string;
  /** Start index of the match in the original text. */
  start: number;
  /** End index (exclusive) of the match in the original text. */
  end: number;
}

/** Return true when `text` looks like a single local file path. */
export function isLocalPath(text: string): boolean {
  const trimmed = text.trim();
  if (!trimmed) return false;
  LOCAL_PATH_RE.lastIndex = 0;
  const m = LOCAL_PATH_RE.exec(trimmed);
  if (!m) return false;
  // The match should span the entire trimmed text.
  return m.index === 0 && m[0].length === trimmed.length;
}

/** Find all local-path occurrences in `text`. */
export function findLocalPaths(text: string): LocalPathMatch[] {
  const results: LocalPathMatch[] = [];
  LOCAL_PATH_RE.lastIndex = 0;

  let m: RegExpExecArray | null;
  while ((m = LOCAL_PATH_RE.exec(text)) !== null) {
    const raw = m[0];
    const cleaned = raw.replace(TRAILING_PUNCT_RE, "");
    if (cleaned.length > 0) {
      results.push({
        path: cleaned,
        start: m.index,
        end: m.index + cleaned.length,
      });
    }
  }

  return results;
}

/**
 * Normalize a detected path:
 * - Strip trailing punctuation that likely isn't part of the path.
 * - Keep the original separator style (no conversion).
 */
export function normalizeLocalPath(raw: string): string {
  return raw.trim().replace(TRAILING_PUNCT_RE, "");
}

// ---------------------------------------------------------------------------
// Explorer opener
// ---------------------------------------------------------------------------

/**
 * Ask the desktop backend to open the given path in the system file explorer.
 *
 * Supports both the Tauri and legacy pywebview desktop runtimes.
 * Only works inside the Desktop app (`isDesktopApp()`).  In the browser this
 * is a no-op so callers don't need to guard the call site.
 */
export async function openInExplorer(path: string): Promise<void> {
  if (!isDesktopApp()) return;

  const normalized = normalizeLocalPath(path);
  if (!normalized) return;

  // Try the legacy pywebview bridge first (it takes precedence when present).
  const pywebviewApi = getPyWebViewApi();
  if (pywebviewApi?.open_in_explorer) {
    try {
      await pywebviewApi.open_in_explorer(normalized);
      return;
    } catch (err) {
      console.warn("[local-path] pywebview open_in_explorer failed:", err);
      return;
    }
  }

  // Fall back to the Tauri command.
  try {
    await invoke("open_in_explorer", { path: normalized });
  } catch (err) {
    console.warn("[local-path] open_in_explorer failed:", err);
  }
}
