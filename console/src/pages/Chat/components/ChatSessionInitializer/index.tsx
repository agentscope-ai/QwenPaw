import React, { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  useChatAnywhereSessionsState,
  type IAgentScopeRuntimeWebUIRef,
} from "@agentscope-ai/chat";
import sessionApi from "../../sessionApi";
import {
  buildChatPath,
  getSessionIdFromPath,
} from "../../../../utils/sessionRoute";
import {
  useSessionListStore,
  type ExtendedSession,
} from "../../../../stores/sessionListStore";
import { useCreateNewSession } from "../../hooks/useCreateNewSession";
import { useAgentStore } from "../../../../stores/agentStore";
import { replaceRuntimeMessageSnapshot } from "../../runtimeMessageSnapshot";

interface ChatSessionInitializerProps {
  runtimeRef?: React.RefObject<IAgentScopeRuntimeWebUIRef | null>;
}

/**
 * URL chatId → context currentSessionId (one direction of bidirectional sync).
 *
 * Extracts the session ID from the canonical `/chat/<id>` URL.
 *
 * The URL is the selection authority. History reads must not navigate elsewhere.
 * Compare the resolved SDK id before updating: list polling is a no-op when in
 * sync, but a stale SDK selection after completion must still be corrected.
 *
 * Also handles sidebar events:
 *  - qwenpaw:sidebar-select-session → switch to the given sessionId
 *  - qwenpaw:sidebar-new-chat       → create a new session
 */
const ChatSessionInitializer: React.FC<ChatSessionInitializerProps> = ({
  runtimeRef,
}) => {
  const location = useLocation();
  const navigate = useNavigate();
  const chatId = useMemo(
    () => getSessionIdFromPath(location.pathname),
    [location.pathname],
  );

  const { sessions, currentSessionId, setCurrentSessionId, setSessions } =
    useChatAnywhereSessionsState();
  const createNewSession = useCreateNewSession();
  const { syncFromLibrary } = useSessionListStore();
  const selectedAgent = useAgentStore((state) => state.selectedAgent);

  // Persist canonical, accessible URL selections even when SDK callbacks skip
  // an already-loaded session. Polling must not trigger another navigation.
  useEffect(() => {
    if (!chatId || !selectedAgent) return;
    if (sessionApi.getActiveOwner().agentId !== selectedAgent) return;
    const matching = sessions.find(
      (entry) =>
        entry.id === chatId || (entry as ExtendedSession).realId === chatId,
    );
    if (!matching) return;
    const id = (matching as ExtendedSession).realId || matching.id;
    if (/^\d+(?:-[a-z0-9]+)?$/.test(id)) return;
    const store = useAgentStore.getState();
    if (
      store.lastChatIdByAgent[selectedAgent] !== id ||
      sessionApi.lastActiveChatId !== id
    ) {
      sessionApi.trackNavigatedSession(id, store.setLastChatId, selectedAgent);
    }
  }, [chatId, sessions, selectedAgent]);

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

  const sessionsRef = useRef(sessions);
  sessionsRef.current = sessions;

  const createNewSessionRef = useRef(createNewSession);
  createNewSessionRef.current = createNewSession;

  /** AbortController for embedded session switch — aborted when a new switch starts. */
  const switchControllerRef = useRef<AbortController | null>(null);

  const [switchCompletion, setSwitchCompletion] = useState(0);
  useEffect(() => {
    // The singleton lock is not React state. Retry a deferred URL selection
    // when it is released, even if the SDK session list has not changed.
    const handleSwitchDone = () => setSwitchCompletion((value) => value + 1);
    window.addEventListener("qwenpaw:sidebar-switch-done", handleSwitchDone);
    return () =>
      window.removeEventListener(
        "qwenpaw:sidebar-switch-done",
        handleSwitchDone,
      );
  }, []);

  useEffect(() => {
    if (!chatId || !sessions.length) return;

    // Issue #4557: Do NOT trigger setCurrentSessionId while a user-initiated
    // session switch is in progress. This breaks the infinite loop where
    // onSessionSelected → navigate → this effect → setCurrentSessionId →
    // library getSession → onSessionSelected → …
    if (sessionApi.isSessionSwitching) return;

    // A navigation marker acknowledges the URL, not the SDK's displayed session.
    if (sessionApi.lastNavigatedChatId === chatId) {
      sessionApi.lastNavigatedChatId = null;
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

    if (matching && currentSessionId !== matching.id) {
      setCurrentSessionId(matching.id);
    }
  }, [
    chatId,
    sessions,
    currentSessionId,
    setCurrentSessionId,
    switchCompletion,
  ]);

  // The sessions context survives route changes while the SDK message provider
  // is mounted anew. In that state the selected id already matches the URL, so
  // setCurrentSessionId is intentionally a no-op and the page would show the
  // new-chat welcome screen. Restore the persisted snapshot into the empty
  // runtime instead.
  const restoredRuntimeRef = useRef<string | null>(null);
  useEffect(() => {
    if (!runtimeRef?.current || !chatId || !sessions.length) return;
    if (sessionApi.isSessionSwitching) return;

    const matching = sessions.find(
      (session) =>
        session.id === chatId ||
        (session as ExtendedSession).realId === chatId ||
        (session as ExtendedSession).sessionId === chatId,
    );
    if (!matching || currentSessionId !== matching.id) return;
    if (runtimeRef.current.messages.getMessages().length > 0) return;

    const restoreKey = `${selectedAgent || ""}:${matching.id}:${chatId}`;
    if (restoredRuntimeRef.current === restoreKey) return;
    restoredRuntimeRef.current = restoreKey;

    const controller = new AbortController();
    sessionApi
      .preloadSession(matching.id, controller.signal)
      .then(({ session }) => {
        if (controller.signal.aborted || !runtimeRef.current) return;
        if (runtimeRef.current.messages.getMessages().length > 0) return;
        replaceRuntimeMessageSnapshot(
          runtimeRef.current.messages,
          session.messages || [],
        );
      })
      .catch((error) => {
        if (error?.name !== "AbortError") {
          restoredRuntimeRef.current = null;
          console.debug("[Chat route restore] skipped:", error);
        }
      });

    return () => controller.abort();
  }, [
    chatId,
    currentSessionId,
    runtimeRef,
    selectedAgent,
    sessions,
    switchCompletion,
  ]);

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
            const targetUrl = buildChatPath(effectiveId);
            sessionApi.trackNavigatedSession(effectiveId);
            sessionApi.preferredChatId = effectiveId;
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
      // Abort any in-flight embedded switch so a late preload result cannot
      // navigate after this initializer (and its chat view) is gone. The
      // aborted promise's finally skips finishSessionSwitch, and the ref
      // always points at the newest switch started by this instance, so
      // releasing the lock here cannot unlock someone else's switch.
      const controller = switchControllerRef.current;
      if (controller && !controller.signal.aborted) {
        controller.abort();
        sessionApi.finishSessionSwitch();
      }
      switchControllerRef.current = null;
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
