import React, { useEffect, useMemo, useRef } from "react";
import { useLocation } from "react-router-dom";
import { useChatAnywhereSessionsState } from "@agentscope-ai/chat";
import sessionApi from "../../sessionApi";
import { getSessionIdFromPath } from "../../../../utils/sessionRoute";

/**
 * URL chatId → context currentSessionId (one direction of bidirectional sync).
 *
 * Extracts sessionId from both `/chat/<id>` and `/coding/<id>` URLs so that
 * Coding mode sessions survive page refreshes (issue #5142).
 *
 * Only reacts to URL or session list changes. currentSessionId is read via ref
 * to avoid triggering the effect when the context changes from the other direction
 * (context → URL via onSessionSelected), which would cause circular re-loads.
 *
 * IMPORTANT: sessions array reference changes (e.g. from polling in pinned drawer)
 * must NOT re-trigger setCurrentSessionId when the chatId hasn't changed, otherwise
 * it causes an infinite loop of getSession calls bouncing between two chat IDs.
 */
const ChatSessionInitializer: React.FC = () => {
  const location = useLocation();

  // Issue #5142: Match both /chat/<id> and /coding/<id> so that Coding mode
  // sessions are restored from the URL on page refresh, just like Chat mode.
  const chatId = useMemo(
    () => getSessionIdFromPath(location.pathname),
    [location.pathname],
  );

  const { sessions, currentSessionId, setCurrentSessionId } =
    useChatAnywhereSessionsState();

  const currentSessionIdRef = useRef(currentSessionId);
  currentSessionIdRef.current = currentSessionId;

  /** Track the last chatId for which we called setCurrentSessionId, so that
   *  subsequent sessions array reference changes (from polling in pinned drawer)
   *  don't re-trigger setCurrentSessionId and cause infinite getSession loops. */
  const lastAppliedChatIdRef = useRef<string | undefined>(undefined);

  useEffect(() => {
    if (!chatId || !sessions.length) return;

    // Issue #4557: Do NOT trigger setCurrentSessionId while a user-initiated
    // session switch is in progress. This breaks the infinite loop where
    // onSessionSelected → navigate → this effect → setCurrentSessionId →
    // library getSession → onSessionSelected → …
    if (sessionApi.isSessionSwitching) return;

    // If onSessionSelected already navigated to this chatId, skip.
    // This prevents the displayId→realId URL change from triggering
    // an unnecessary setCurrentSessionId(realId) that would cause
    // a redundant getSession call (issue #4557).
    if (sessionApi.lastNavigatedChatId === chatId) {
      lastAppliedChatIdRef.current = chatId;
      sessionApi.lastNavigatedChatId = null;
      return;
    }

    // If we already applied this exact chatId and the context is in sync, skip.
    // This prevents the polling-triggered sessions refresh (pinned drawer)
    // from re-calling setCurrentSessionId and causing circular getSession loops.
    if (chatId === lastAppliedChatIdRef.current) {
      return;
    }

    const matching = sessions.find((s) => s.id === chatId);
    if (matching && currentSessionIdRef.current !== matching.id) {
      lastAppliedChatIdRef.current = chatId;
      setCurrentSessionId(matching.id);
    } else if (matching) {
      // Already in sync, just record that we've handled this chatId
      lastAppliedChatIdRef.current = chatId;
    }
    // Intentionally exclude currentSessionId from deps: only react to URL / session list changes.
    // currentSessionId is read via ref to avoid circular triggers.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatId, sessions, setCurrentSessionId]);

  return null;
};

export default ChatSessionInitializer;
