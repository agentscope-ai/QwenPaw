import React, { useEffect, useMemo, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  useChatAnywhereSessionsState,
  useChatAnywhereSessions,
} from "@agentscope-ai/chat";
import sessionApi from "../../sessionApi";
import {
  buildSessionPath,
  getSessionIdFromPath,
} from "../../../../utils/sessionRoute";
import { useCodingMode } from "../../../../stores/codingModeStore";
import {
  useSessionListStore,
  type ExtendedSession,
} from "../../../../stores/sessionListStore";

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
 *
 * Also handles sidebar events:
 *  - qwenpaw:sidebar-select-session → switch to the given sessionId
 *  - qwenpaw:sidebar-new-chat       → create a new session
 */
const ChatSessionInitializer: React.FC = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const { codingMode } = useCodingMode();

  // Issue #5142: Match both /chat/<id> and /coding/<id> so that Coding mode
  // sessions are restored from the URL on page refresh, just like Chat mode.
  const chatId = useMemo(
    () => getSessionIdFromPath(location.pathname),
    [location.pathname],
  );

  const { sessions, currentSessionId, setCurrentSessionId, setSessions } =
    useChatAnywhereSessionsState();
  const { createSession } = useChatAnywhereSessions();
  const { syncFromLibrary } = useSessionListStore();

  // Sync library sessions → shared Zustand store whenever they change.
  // This makes the session list available to components outside the context tree
  // (e.g. SidebarSessionList in simple-mode sidebar).
  useEffect(() => {
    syncFromLibrary(
      sessions as ExtendedSession[],
      setSessions as (s: ExtendedSession[]) => void,
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessions]);

  const currentSessionIdRef = useRef(currentSessionId);
  currentSessionIdRef.current = currentSessionId;

  const sessionsRef = useRef(sessions);
  sessionsRef.current = sessions;

  const codingModeRef = useRef(codingMode);
  codingModeRef.current = codingMode;

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

  // ── Sidebar event handlers ────────────────────────────────────────────────

  useEffect(() => {
    /**
     * Handle sidebar session selection.
     * The sidebar dispatches this event when the user clicks a session item,
     * since the sidebar is outside the AgentScopeRuntimeWebUI context tree
     * and cannot call setCurrentSessionId directly.
     */
    const handleSelectSession = (e: Event) => {
      const sessionId = (e as CustomEvent<{ sessionId: string }>).detail
        .sessionId;
      if (!sessionId) return;

      const mode = codingModeRef.current ? "coding" : "chat";
      const currentSessions = sessionsRef.current;
      const matching = currentSessions.find((s) => s.id === sessionId);

      if (matching) {
        // Preload then navigate + sync, mirroring ChatSessionDrawer behaviour.
        sessionApi.isSessionSwitching = true;
        sessionApi
          .preloadSession(sessionId)
          .then(({ realId }) => {
            const effectiveId = realId || sessionId;
            const targetUrl = buildSessionPath(mode, effectiveId);
            sessionApi.lastNavigatedChatId = effectiveId;
            navigate(targetUrl, { replace: true });
            setCurrentSessionId(sessionId);
          })
          .catch(() => {
            // Fallback: just set the session id; URL sync via onSessionSelected
            setCurrentSessionId(sessionId);
          })
          .finally(() => {
            requestAnimationFrame(() => {
              requestAnimationFrame(() => {
                sessionApi.finishSessionSwitch();
              });
            });
          });
      }
    };

    /**
     * Handle new-chat request from sidebar.
     * Creates a fresh session via the library's createSession().
     */
    const handleNewChat = () => {
      void createSession();
    };

    window.addEventListener(
      "qwenpaw:sidebar-select-session",
      handleSelectSession,
    );
    window.addEventListener("qwenpaw:sidebar-new-chat", handleNewChat);

    return () => {
      window.removeEventListener(
        "qwenpaw:sidebar-select-session",
        handleSelectSession,
      );
      window.removeEventListener("qwenpaw:sidebar-new-chat", handleNewChat);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [navigate, setCurrentSessionId, createSession]);

  return null;
};

export default ChatSessionInitializer;
