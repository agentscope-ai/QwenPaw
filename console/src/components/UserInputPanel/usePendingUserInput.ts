import { useCallback, useEffect, useRef, useState } from "react";
import {
  subscribeUserInputUpdates,
  userInputApi,
  type UserInputRequest,
} from "../../api/modules/userInput";

function getBackendSessionId(): string {
  return (window as any).currentSessionId || "";
}

export function usePendingUserInput(active: boolean) {
  const [request, setRequest] = useState<UserInputRequest | null>(null);
  const [loading, setLoading] = useState(false);
  const prevBackendSidRef = useRef("");

  const fetchPending = useCallback(async () => {
    const sid = getBackendSessionId();
    if (sid !== prevBackendSidRef.current) {
      prevBackendSidRef.current = sid;
      setRequest(null);
    }
    if (!sid) return;
    setLoading(true);
    try {
      const data = await userInputApi.getPending(sid);
      setRequest(data);
    } catch {
      // ignore transient polling errors
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!active) {
      setRequest(null);
      return;
    }
    fetchPending();
  }, [active, fetchPending]);

  useEffect(() => {
    if (!active) return;

    const unsub = subscribeUserInputUpdates(
      (updated, eventSessionId, eventRootSessionId) => {
        const mySid = getBackendSessionId();
        if (
          mySid &&
          eventSessionId &&
          eventRootSessionId &&
          eventSessionId !== mySid &&
          eventRootSessionId !== mySid
        ) {
          return;
        }
        setRequest(updated);
      },
    );

    return () => unsub();
  }, [active]);

  useEffect(() => {
    if (!active) return;
    const interval = setInterval(fetchPending, 5000);
    return () => clearInterval(interval);
  }, [active, fetchPending]);

  return { request, loading, refresh: fetchPending };
}
