import { useEffect } from "react";
import sessionApi from "../../pages/Chat/sessionApi";
import { useAgentStore } from "../../stores/agentStore";
import {
  SESSION_LIST_REFRESH_EVENT,
  syncSessionsGlobal,
  useSessionListStore,
  type ExtendedSession,
} from "../../stores/sessionListStore";

const REFRESH_INTERVAL_MS = 10000;
const BACKGROUND_REFRESH_INTERVAL_MS = 30000;

/** Keep session metadata fresh independently of sidebar visibility. */
export function SessionListPollingController() {
  const selectedAgent = useAgentStore((state) => state.selectedAgent);

  useEffect(() => {
    let cancelled = false;
    let inFlight = false;
    let refreshAfterFlight = false;
    let lastFetchAt = 0;
    let lastSessions: ExtendedSession[] | undefined;
    const owner = sessionApi.getActiveOwner();

    const fetchSessions = async (showLoading = false) => {
      if (inFlight || sessionApi.isSessionSwitching) return;
      refreshAfterFlight = false;
      inFlight = true;
      lastFetchAt = Date.now();
      if (showLoading) useSessionListStore.setState({ loading: true });
      try {
        const list = (await sessionApi.getSessionList()) as ExtendedSession[];
        if (!cancelled && sessionApi.isActiveOwner(owner)) {
          // SessionApi preserves this reference when metadata is unchanged.
          if (list !== lastSessions) {
            lastSessions = list;
            syncSessionsGlobal(list);
          }
        }
      } catch (error) {
        if (showLoading)
          console.error(
            "SessionListPollingController: failed to fetch sessions",
            error,
          );
      } finally {
        inFlight = false;
        if (
          !cancelled &&
          sessionApi.isActiveOwner(owner) &&
          useSessionListStore.getState().loading
        )
          useSessionListStore.setState({ loading: false });
        if (!cancelled && refreshAfterFlight) {
          void fetchSessions();
        }
      }
    };

    const onSessionListRefresh = () => {
      if (inFlight || sessionApi.isSessionSwitching) {
        refreshAfterFlight = true;
        return;
      }
      void fetchSessions();
    };

    const onSessionSwitchDone = () => {
      if (refreshAfterFlight) void fetchSessions();
    };

    void fetchSessions(true);
    const timer = setInterval(() => {
      if (
        document.hidden &&
        Date.now() - lastFetchAt < BACKGROUND_REFRESH_INTERVAL_MS
      )
        return;
      void fetchSessions();
    }, REFRESH_INTERVAL_MS);

    const onVisibility = () => {
      if (!document.hidden) void fetchSessions(true);
    };
    document.addEventListener("visibilitychange", onVisibility);
    document.addEventListener(SESSION_LIST_REFRESH_EVENT, onSessionListRefresh);
    window.addEventListener("qwenpaw:sidebar-switch-done", onSessionSwitchDone);

    return () => {
      cancelled = true;
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibility);
      document.removeEventListener(
        SESSION_LIST_REFRESH_EVENT,
        onSessionListRefresh,
      );
      window.removeEventListener(
        "qwenpaw:sidebar-switch-done",
        onSessionSwitchDone,
      );
    };
  }, [selectedAgent]);

  return null;
}
