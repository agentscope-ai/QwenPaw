/**
 * Helpers for cursor-based chat history pagination.
 *
 * The backend windows GET /api/chats/{chat_id} by `limit` + `before`, where
 * `before` is `metadata.original_id` (the persistent AgentScope Msg id).
 * `Message.id` is regenerated on every request and cannot be a cursor.
 * One Msg can expand into several Message objects that share original_id;
 * the cursor cuts at the first occurrence so groups are never split.
 */

import type { Message } from "../../../api";

/** Default window size when opening or paging a chat. */
export const DEFAULT_HISTORY_PAGE_SIZE = 50;

export interface HistoryPageState {
  hasMore: boolean;
  loading: boolean;
  total: number;
  oldestOriginalId: string | null;
  loadedOriginalIds: string[];
}

export const EMPTY_HISTORY_PAGE: HistoryPageState = {
  hasMore: false,
  loading: false,
  total: 0,
  oldestOriginalId: null,
  loadedOriginalIds: [],
};

/** Read `metadata.original_id` from a backend chat message. */
export function messageOriginalId(message: Message): string | null {
  const metadata = message.metadata;
  if (!metadata || typeof metadata !== "object") return null;
  const value = (metadata as { original_id?: unknown }).original_id;
  return typeof value === "string" && value.length > 0 ? value : null;
}

/** Oldest source-message id in an oldest-first window. */
export function oldestSourceOriginalId(messages: Message[]): string | null {
  for (const message of messages) {
    const originalId = messageOriginalId(message);
    if (originalId) return originalId;
  }
  return null;
}

/** Unique original_ids in oldest-first order, keeping group identity. */
export function collectOriginalIds(messages: Message[]): string[] {
  const ids: string[] = [];
  const seen = new Set<string>();
  for (const message of messages) {
    const originalId = messageOriginalId(message);
    if (!originalId || seen.has(originalId)) continue;
    seen.add(originalId);
    ids.push(originalId);
  }
  return ids;
}

/**
 * Keep messages that are not already loaded. Drops a whole original_id
 * group when any segment of it is already on screen, so groups stay intact.
 */
export function takeUniqueOlderMessages(
  older: Message[],
  loadedOriginalIds: readonly string[],
): Message[] {
  const loaded = new Set(loadedOriginalIds);
  const skippedGroups = new Set<string>();
  const kept: Message[] = [];
  for (const message of older) {
    const originalId = messageOriginalId(message);
    if (
      originalId &&
      (loaded.has(originalId) || skippedGroups.has(originalId))
    ) {
      skippedGroups.add(originalId);
      continue;
    }
    kept.push(message);
  }
  return kept;
}

export function historyPageFromMessages(
  messages: Message[],
  hasMore: boolean,
  total: number,
  loading = false,
): HistoryPageState {
  return {
    hasMore,
    loading,
    total,
    oldestOriginalId: oldestSourceOriginalId(messages),
    loadedOriginalIds: collectOriginalIds(messages),
  };
}

/**
 * Snapshot/restore scroll after older messages are prepended.
 * Reverse lists (negative scrollTop) stay anchored to the newest edge
 * when scrollTop is left unchanged; top-origin lists need the height delta.
 */
export function restoreScrollAfterPrepend(
  scroller: {
    scrollTop: number;
    scrollHeight: number;
  },
  previousScrollTop: number,
  previousScrollHeight: number,
): number {
  const heightDelta = scroller.scrollHeight - previousScrollHeight;
  if (previousScrollTop <= 0 && scroller.scrollTop <= 0) {
    return previousScrollTop;
  }
  return previousScrollTop + Math.max(0, heightDelta);
}
