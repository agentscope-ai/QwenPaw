/**
 * Pure helpers for the Chat input draft persistence.
 *
 * Extracted from Chat/index.tsx so the draft contract can be unit-tested
 * without rendering the (very large) Chat page. The draft hook
 * (`useChatInputDraft`) stays in index.tsx and consumes these helpers;
 * behaviour is unchanged.
 *
 * Regressions guarded here:
 * - A#82689956: drafts must be isolated per agent (storage key carries the
 *   agent id), otherwise switching agents leaks one agent's draft into
 *   another's input box.
 * - #4774: navigating away and back must restore the draft exactly (value +
 *   cursor selection), and malformed/empty stored data must never throw.
 */

export const DRAFT_STORAGE_KEY_PREFIX = "qwenpaw_chat_input_draft";

export interface DraftState {
  value: string;
  selectionStart: number;
  selectionEnd: number;
}

/**
 * Storage key for an agent's draft. With an agent id the key is namespaced
 * (`qwenpaw_chat_input_draft_<agentId>`); without one it falls back to the
 * shared key. Distinct keys per agent are what keep drafts from leaking
 * across agents (A#82689956).
 */
export function getDraftStorageKey(agentId?: string): string {
  return agentId
    ? `${DRAFT_STORAGE_KEY_PREFIX}_${agentId}`
    : DRAFT_STORAGE_KEY_PREFIX;
}

/**
 * Serializes a draft for persistence. Returns null when the value is empty —
 * callers must treat null as "remove the stored draft" (a leftover stale
 * draft would resurface on the next visit, regression #4774).
 */
export function serializeDraft(draft: DraftState): string | null {
  return draft.value ? JSON.stringify(draft) : null;
}

/**
 * Parses a stored draft. Returns null for missing, malformed, or empty
 * values — restore must fail soft and never throw on corrupted storage.
 */
export function parseDraft(raw: string | null): DraftState | null {
  if (!raw) return null;
  try {
    const draft = JSON.parse(raw) as DraftState;
    return draft.value ? draft : null;
  } catch {
    return null;
  }
}
