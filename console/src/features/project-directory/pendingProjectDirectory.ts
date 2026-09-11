/**
 * Pending (not-yet-persisted) Session project directories.
 *
 * A brand-new chat has no backend chat id yet, so its project-directory
 * selection cannot be PUT anywhere. Instead it is held in sessionStorage,
 * keyed by agent + local session id, and rides along with the first message
 * (as `session_project_dirs` in the request context); the console router
 * then persists it onto the chat.
 *
 * The stored value is an ordered list, index 0 being PRIMARY. Legacy
 * single-string entries — written before the list existed — are read back as
 * a one-entry list so existing sessionStorage values keep working.
 */
const KEY_PREFIX = "qwenpaw-session-project-dir:";

export interface PendingProjectDirEntry {
  path: string;
  label: string | null;
}

export interface PendingProjectDirsValue {
  dirs: PendingProjectDirEntry[];
}

function storageKey(agentId: string, sessionId: string): string {
  return `${KEY_PREFIX}${agentId}:${sessionId}`;
}

function toEntry(raw: unknown): PendingProjectDirEntry | null {
  if (!raw || typeof raw !== "object") return null;
  const entry = raw as { path?: unknown; label?: unknown };
  if (typeof entry.path !== "string" || !entry.path) return null;
  return {
    path: entry.path,
    label: typeof entry.label === "string" ? entry.label : null,
  };
}

/** Read and normalise the stored value, accepting the legacy string form. */
function readValue(
  agentId: string,
  sessionId: string,
): PendingProjectDirsValue | null {
  const raw = sessionStorage.getItem(storageKey(agentId, sessionId));
  if (raw === null || raw === "") return null;

  try {
    const parsed: unknown = JSON.parse(raw);
    if (
      parsed &&
      typeof parsed === "object" &&
      Array.isArray((parsed as { dirs?: unknown }).dirs)
    ) {
      const dirs = (parsed as { dirs: unknown[] }).dirs
        .map(toEntry)
        .filter((entry): entry is PendingProjectDirEntry => entry !== null);
      if (dirs.length === 0) return null;
      return { dirs };
    }
    // Valid JSON but not the structured shape (e.g. a JSON-encoded string):
    // fall through and treat it as a legacy path below.
    if (typeof parsed === "string" && parsed) {
      return { dirs: [{ path: parsed, label: null }] };
    }
    return null;
  } catch {
    // Legacy plain-string value: a single path written before the list.
    return { dirs: [{ path: raw, label: null }] };
  }
}

/** Structured getter: the whole pending list, or null when none is pending. */
export function getPendingProjectDirs(
  agentId: string,
  sessionId: string,
): PendingProjectDirsValue | null {
  return readValue(agentId, sessionId);
}

/**
 * Primary-directory getter. Returns the first (primary) path, or null.
 *
 * Kept returning a single path because long-standing callers (the Files
 * workspace/navigator and the Chat page) consume it as a string and only
 * ever show the primary directory.
 */
export function getPendingProjectDirectory(
  agentId: string,
  sessionId: string,
): string | null {
  return readValue(agentId, sessionId)?.dirs[0]?.path ?? null;
}

/** Store the pending list. Passing null or an empty list clears the entry. */
export function setPendingProjectDirectory(
  agentId: string,
  sessionId: string,
  dirs: PendingProjectDirEntry[] | null,
): void {
  const key = storageKey(agentId, sessionId);
  if (!dirs || dirs.length === 0) {
    sessionStorage.removeItem(key);
    return;
  }
  const value: PendingProjectDirsValue = {
    dirs: dirs.map((entry) => ({
      path: entry.path,
      label: entry.label ?? null,
    })),
  };
  sessionStorage.setItem(key, JSON.stringify(value));
}

export function migratePendingProjectDirectory(
  agentId: string,
  fromSessionId: string,
  toSessionId: string,
): void {
  if (fromSessionId === toSessionId) return;
  const value = readValue(agentId, fromSessionId);
  if (!value) return;
  setPendingProjectDirectory(agentId, toSessionId, value.dirs);
  setPendingProjectDirectory(agentId, fromSessionId, null);
}

export function withPendingProjectDirectory(
  requestBody: Record<string, unknown>,
  agentId: string,
  sessionId: string,
): {
  requestBody: Record<string, unknown>;
  projectDir: string | null;
} {
  const value = readValue(agentId, sessionId);
  if (!value || value.dirs.length === 0) {
    return { requestBody, projectDir: null };
  }
  const projectDir = value.dirs[0]?.path ?? null;
  const currentContext =
    requestBody.request_context &&
    typeof requestBody.request_context === "object"
      ? (requestBody.request_context as Record<string, unknown>)
      : {};
  const sessionProjectDirs = value.dirs.map((entry) => ({
    path: entry.path,
    label: entry.label ?? null,
  }));
  const nextContext: Record<string, unknown> = {
    ...currentContext,
    session_project_dirs: sessionProjectDirs,
  };
  return {
    requestBody: {
      ...requestBody,
      request_context: nextContext,
    },
    projectDir,
  };
}
