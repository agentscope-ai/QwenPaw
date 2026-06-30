import React, { useEffect, useMemo, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useChatAnywhereSessionsState } from "@agentscope-ai/chat";
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
import { useCreateNewSession } from "../../hooks/useCreateNewSession";

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
  const createNewSession = useCreateNewSession();
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

  const createNewSessionRef = useRef(createNewSession);
  createNewSessionRef.current = createNewSession;

  /** AbortController for embedded session switch — aborted when a new switch starts. */
  const switchControllerRef = useRef<AbortController | null>(null);

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

    // Match by multiple criteria in order of specificity:
    // 1) Library id (localId or UUID)
    let matching = sessions.find((s) => s.id === chatId);

    // 2) realId: URL contains a UUID but the session's library id is still a
    //    local timestamp (e.g. during SSE before onSessionIdResolved fires).
    if (!matching) {
      matching = sessions.find((s) => (s as ExtendedSession).realId === chatId);
    }

    // 3) sessionId field: URL contains the backend session_id format
    if (!matching) {
      matching = sessions.find(
        (s) => (s as ExtendedSession).sessionId === chatId,
      );
    }

    if (matching && currentSessionIdRef.current !== matching.id) {
      lastAppliedChatIdRef.current = chatId;
      setCurrentSessionId(matching.id);
    } else if (matching) {
      // Already in sync, just record that we've handled this chatId
      lastAppliedChatIdRef.current = chatId;
    }
    // Intentionally exclude currentSessionId from deps: only react to URL / session list changes.
    // currentSessionId is read via ref to avoid circular triggers.
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
        // Abort any previous embedded switch
        switchControllerRef.current?.abort();
        const controller = new AbortController();
        switchControllerRef.current = controller;

        sessionApi.isSessionSwitching = true;
        sessionApi
          .preloadSession(sessionId, controller.signal)
          .then(({ realId }) => {
            if (controller.signal.aborted) return;
            const effectiveId = sessionApi.getEffectiveSessionId(
              sessionId,
              realId,
            );
            const targetUrl = buildSessionPath(mode, effectiveId);
            sessionApi.trackNavigatedSession(effectiveId);
            navigate(targetUrl, { replace: true });
            setCurrentSessionId(sessionId);
          })
          .catch((err) => {
            if (err?.name === "AbortError") return;
            setCurrentSessionId(sessionId);
          })
          .finally(() => {
            if (!controller.signal.aborted) {
              sessionApi.finishSessionSwitch();
              window.dispatchEvent(
                new CustomEvent("qwenpaw:sidebar-switch-done"),
              );
            }
          });
      }
    };

    const handleNewChat = () => {
      if (sessionApi.isSessionSwitching) {
        sessionApi.finishSessionSwitch();
      }
      void createNewSessionRef.current();
    };

    window.addEventListener(
      "qwenpaw:sidebar-select-session",
      handleSelectSession,
    );
    window.addEventListener("qwenpaw:sidebar-new-chat", handleNewChat);

    // Check for pending new-chat flag set by Sidebar when navigating from
    // another page. Must be deferred so the library has initialized.
    const pendingNewChat = sessionStorage.getItem("qwenpaw_pending_new_chat");
    if (pendingNewChat) {
      sessionStorage.removeItem("qwenpaw_pending_new_chat");
      requestAnimationFrame(() => handleNewChat());
    }

    return () => {
      window.removeEventListener(
        "qwenpaw:sidebar-select-session",
        handleSelectSession,
      );
      window.removeEventListener("qwenpaw:sidebar-new-chat", handleNewChat);
    };
  }, [navigate, setCurrentSessionId]);

  return null;
};

export default ChatSessionInitializer;
