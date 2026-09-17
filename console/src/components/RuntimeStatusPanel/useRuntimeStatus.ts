import { useCallback, useEffect, useRef, useState } from "react";
import {
  runtimeStatusApi,
  subscribeRuntimeStatusUpdates,
  type RuntimeStatus,
} from "../../api/modules/runtimeStatus";

function getBackendSessionId(): string {
  return (window as any).currentSessionId || "";
}

export function useRuntimeStatus(active: boolean) {
  const [status, setStatus] = useState<RuntimeStatus | null>(null);
  const prevBackendSidRef = useRef("");

  const fetchStatus = useCallback(async () => {
    const sid = getBackendSessionId();
    if (sid !== prevBackendSidRef.current) {
      prevBackendSidRef.current = sid;
      setStatus(null);
    }
    if (!sid) return;
    try {
      const data = await runtimeStatusApi.getCurrent(sid);
      setStatus(data);
    } catch {
      // ignore transient polling errors
    }
  }, []);

  useEffect(() => {
    if (!active) {
      setStatus(null);
      return;
    }
    fetchStatus();
  }, [active, fetchStatus]);

  useEffect(() => {
    if (!active) return;
    const unsub = subscribeRuntimeStatusUpdates(
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
        setStatus(updated);
      },
    );
    return () => unsub();
  }, [active]);

  useEffect(() => {
    if (!active) return;
    const interval = setInterval(fetchStatus, 5000);
    return () => clearInterval(interval);
  }, [active, fetchStatus]);

  return { status, refresh: fetchStatus };
}
