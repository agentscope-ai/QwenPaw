/**
 * Console-local chat history page size (N).
 *
 * Stored in localStorage, not in channels.console — those fields are
 * outbound IM rendering (thinking / tool calls), not WebUI fetch windows.
 * Matches GET /api/chats/{id} `limit`: integer 1–10000, default 50.
 */

export const HISTORY_PAGE_SIZE_STORAGE_KEY = "qwenpaw_chat_history_page_size";
export const DEFAULT_HISTORY_PAGE_SIZE = 50;
export const HISTORY_PAGE_SIZE_MIN = 1;
export const HISTORY_PAGE_SIZE_MAX = 10000;

const listeners = new Set<() => void>();
let snapshot: number | null = null;

function getStorage(): Storage | null {
  return typeof window === "undefined" ? null : window.localStorage;
}

function emit(): void {
  listeners.forEach((listener) => listener());
}

/** Parse user/storage input. Empty, NaN, and non-numeric values are invalid. */
export function parseHistoryPageSize(raw: unknown): number | null {
  if (raw === null || raw === undefined) return null;
  if (typeof raw === "string" && raw.trim() === "") return null;
  if (typeof raw === "boolean") return null;
  const value = typeof raw === "number" ? raw : Number(raw);
  if (!Number.isFinite(value)) return null;
  return value;
}

export function clampHistoryPageSize(value: number): number {
  const integer = Math.trunc(value);
  if (!Number.isFinite(integer)) return DEFAULT_HISTORY_PAGE_SIZE;
  return Math.min(
    HISTORY_PAGE_SIZE_MAX,
    Math.max(HISTORY_PAGE_SIZE_MIN, integer),
  );
}

function readStored(): number {
  try {
    const raw = getStorage()?.getItem(HISTORY_PAGE_SIZE_STORAGE_KEY);
    const parsed = parseHistoryPageSize(raw);
    if (parsed === null) return DEFAULT_HISTORY_PAGE_SIZE;
    return clampHistoryPageSize(parsed);
  } catch {
    return DEFAULT_HISTORY_PAGE_SIZE;
  }
}

export function getHistoryPageSize(): number {
  if (snapshot === null) snapshot = readStored();
  return snapshot;
}

export function setHistoryPageSize(value: number): {
  value: number;
  changed: boolean;
} {
  const next = clampHistoryPageSize(value);
  const previous = getHistoryPageSize();
  if (next === previous) return { value: next, changed: false };
  snapshot = next;
  try {
    getStorage()?.setItem(HISTORY_PAGE_SIZE_STORAGE_KEY, String(next));
  } catch {
    /* storage unavailable */
  }
  emit();
  return { value: next, changed: true };
}

export function subscribeHistoryPageSize(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Commit a draft. Invalid/empty input returns null so callers can restore. */
export function commitHistoryPageSize(
  raw: unknown,
): { value: number; changed: boolean } | null {
  const parsed = parseHistoryPageSize(raw);
  if (parsed === null) return null;
  return setHistoryPageSize(parsed);
}

export function resetHistoryPageSizeForTests(): void {
  snapshot = null;
  try {
    getStorage()?.removeItem(HISTORY_PAGE_SIZE_STORAGE_KEY);
  } catch {
    /* storage unavailable */
  }
  emit();
}
