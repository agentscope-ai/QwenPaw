/**
 * The one place that answers "are these two paths the same directory?".
 *
 * There used to be three answers. The backend folded case per
 * `sys.platform`, the session picker folded unconditionally, and the Files
 * root switcher folded only `C:/…` drive letters. That disagreement is not
 * cosmetic:
 *
 * - Folding on a Linux server makes `/srv/Repo` look like it is already
 *   bound when `/srv/repo` is. They are two real directories there, and the
 *   user could never bind both.
 * - Not folding a Windows UNC path leaves `\\SERVER\Share\Repo` and
 *   `\\server\share\repo` as two roots for one location, which splits the
 *   editor tabs and dirty state between them.
 *
 * So the *server* decides — it is the side that actually touches the
 * filesystem — and publishes the answer as `path_case_insensitive` on the
 * project-directory responses. This module holds that flag and every
 * comparison built on it.
 *
 * Until the first response arrives the flag is `false`: not folding can
 * only ever show one directory twice, while folding wrongly would merge
 * two distinct directories and drop one of the user's roots. A cosmetic
 * duplicate for one render is the cheaper mistake.
 *
 * Known limitation, shared with the backend on purpose: the flag is
 * per-platform, not per-volume. A case-sensitive APFS volume on macOS, or
 * a directory carrying Windows' per-directory case-sensitivity flag, still
 * compares as folded. Answering that needs a per-path probe on the server;
 * one wrong-but-agreed answer beats three that disagree.
 */

let caseInsensitive = false;

/** Adopt the server's case policy. Called when a snapshot arrives. */
export function setPathCaseInsensitive(value: boolean | undefined): void {
  if (typeof value === "boolean") caseInsensitive = value;
}

/** Whether comparisons currently fold case. Exported for tests. */
export function isPathCaseInsensitive(): boolean {
  return caseInsensitive;
}

/**
 * Canonical comparison form: separators unified, trailing ones dropped,
 * case folded only when the server folds.
 *
 * Backslashes become forward slashes so a Windows path compares the same
 * whichever separator it arrived with — including UNC paths, whose leading
 * `\\` becomes `//` and is preserved rather than collapsed.
 */
export function normalizePathForCompare(path: string): string {
  const unified = path.trim().replace(/\\/g, "/");
  // Keep a UNC prefix intact while still stripping a trailing separator.
  const prefix = unified.startsWith("//") ? "//" : "";
  const body = unified.slice(prefix.length).replace(/\/+$/, "");
  const normalized = prefix + body;
  return caseInsensitive ? normalized.toLowerCase() : normalized;
}

/** Whether two paths name the same directory under the server's rule. */
export function samePath(a: string, b: string): boolean {
  return normalizePathForCompare(a) === normalizePathForCompare(b);
}
