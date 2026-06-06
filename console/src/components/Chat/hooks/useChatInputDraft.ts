import { useCallback, useEffect, useRef } from "react";

// ---------------------------------------------------------------------------
// Chat input draft persistence
//
// Saves unsent text to localStorage so it survives page refreshes and
// session switches.  Each session gets its own draft keyed by session ID.
// ---------------------------------------------------------------------------

const DRAFT_KEY_PREFIX = "qwenpaw_chat_v2_draft";

function draftKey(sessionId: string | null): string {
  return sessionId ? `${DRAFT_KEY_PREFIX}:${sessionId}` : DRAFT_KEY_PREFIX;
}

export interface UseChatInputDraftOptions {
  /** Current session ID – drafts are stored per-session */
  sessionId: string | null;
  /** Current input value (controlled) */
  value: string;
  /** Setter for input value */
  setValue: (value: string) => void;
}

/**
 * Persist unsent input text to localStorage, restoring it when the
 * component mounts or the session changes.
 *
 * Call `clearDraft()` after a successful send to remove the stored text.
 */
export function useChatInputDraft({
  sessionId,
  value,
  setValue,
}: UseChatInputDraftOptions) {
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const restoredSessionRef = useRef<string | null>(null);

  // -- Restore draft when session changes ----------------------------------
  useEffect(() => {
    const key = draftKey(sessionId);
    // Avoid restoring the same session twice (e.g. on re-render)
    if (restoredSessionRef.current === key) return;
    restoredSessionRef.current = key;

    try {
      const saved = localStorage.getItem(key);
      if (saved) {
        setValue(saved);
      } else {
        // Switching to a session with no draft – clear the input
        setValue("");
      }
    } catch {
      // localStorage unavailable – ignore
    }
  }, [sessionId, setValue]);

  // -- Debounced save on value change --------------------------------------
  useEffect(() => {
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);

    saveTimerRef.current = setTimeout(() => {
      const key = draftKey(sessionId);
      try {
        if (value) {
          localStorage.setItem(key, value);
        } else {
          localStorage.removeItem(key);
        }
      } catch {
        // quota exceeded or unavailable – ignore
      }
    }, 300);

    return () => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    };
  }, [value, sessionId]);

  // -- Save synchronously on unmount --------------------------------------
  const valueRef = useRef(value);
  valueRef.current = value;

  const sessionIdRef = useRef(sessionId);
  sessionIdRef.current = sessionId;

  useEffect(() => {
    return () => {
      const key = draftKey(sessionIdRef.current);
      try {
        if (valueRef.current) {
          localStorage.setItem(key, valueRef.current);
        } else {
          localStorage.removeItem(key);
        }
      } catch {
        // ignore
      }
    };
  }, []);

  // -- Clear draft (call after send) --------------------------------------
  const clearDraft = useCallback(() => {
    const key = draftKey(sessionIdRef.current);
    try {
      localStorage.removeItem(key);
    } catch {
      // ignore
    }
  }, []);

  return { clearDraft };
}
