import React, { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useChatAnywhereSessionsState } from "@agentscope-ai/chat";
import sessionApi from "../../sessionApi";
import { buildChatPath } from "../../../../utils/sessionRoute";
import {
  useSessionListStore,
  type ExtendedSession,
} from "../../../../stores/sessionListStore";
import { useCreateNewSession } from "../../hooks/useCreateNewSession";

/**
 * Mirror SDK sessions for the sidebar and translate sidebar intents to routes.
 * ChatPage's controlled session.currentSessionId is the only route-to-SDK
 * writer. A list refresh must never select an old local alias after the route
 * and completed response have moved to a Chat UUID.
 */
const ChatSessionInitializer: React.FC = () => {
  const navigate = useNavigate();
  const { sessions, setSessions } = useChatAnywhereSessionsState();
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

  const sessionsRef = useRef(sessions);
  sessionsRef.current = sessions;

  const createNewSessionRef = useRef(createNewSession);
  createNewSessionRef.current = createNewSession;

  /** AbortController for embedded session switch — aborted when a new switch starts. */
  const switchControllerRef = useRef<AbortController | null>(null);

  // ── Sidebar event handlers ────────────────────────────────────────────────

  useEffect(() => {
    /**
     * Handle sidebar session selection.
     * The sidebar dispatches this event when the user clicks a session item,
     * since the sidebar is outside the AgentScopeRuntimeWebUI context tree
     * and changes the route through this bridge.
     */
    const handleSelectSession = (e: Event) => {
      const sessionId = (e as CustomEvent<{ sessionId: string }>).detail
        .sessionId;
      if (!sessionId) return;

      const currentSessions = sessionsRef.current;
      const matching = currentSessions.find(
        (s) =>
          s.id === sessionId || (s as ExtendedSession).realId === sessionId,
      );

      if (matching) {
        // Abort any previous embedded switch
        const controller = sessionApi.startNewSwitch();
        switchControllerRef.current = controller;

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
          })
          .catch((err) => {
            if (err?.name === "AbortError") return;
            if (controller.signal.aborted) return;
            navigate(
              buildChatPath(sessionApi.getEffectiveSessionId(sessionId)),
              {
                replace: true,
              },
            );
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
      switchControllerRef.current?.abort();
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
  }, [navigate]);

  return null;
};

export default ChatSessionInitializer;
