import { useCallback, useEffect, useRef, useState } from "react";
import {
  planApi,
  subscribePlanUpdates,
  type PlanStateResponse,
} from "../../api/modules/plan";

function getBackendSessionId(): string {
  return (window as any).currentSessionId || "";
}

export function useCurrentPlan(active: boolean) {
  const [plan, setPlan] = useState<PlanStateResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const ssePlanRef = useRef<PlanStateResponse | null>(null);
  const prevBackendSidRef = useRef("");

  const fetchPlan = useCallback(async () => {
    const sid = getBackendSessionId();
    if (sid !== prevBackendSidRef.current) {
      prevBackendSidRef.current = sid;
      ssePlanRef.current = null;
      setPlan(null);
    }
    setLoading(true);
    try {
      const data = await planApi.getCurrentPlan(sid || undefined);
      if (ssePlanRef.current !== null && data === null) return;
      setPlan(data);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!active) {
      setPlan(null);
      ssePlanRef.current = null;
      return;
    }
    const backendSid = getBackendSessionId();
    if (backendSid !== prevBackendSidRef.current) {
      prevBackendSidRef.current = backendSid;
      ssePlanRef.current = null;
      setPlan(null);
    }
    fetchPlan();
  }, [active, fetchPlan]);

  useEffect(() => {
    if (!active) return;

    const unsub = subscribePlanUpdates((updatedPlan, eventSessionId) => {
      const mySid = getBackendSessionId();
      if (eventSessionId && mySid && eventSessionId !== mySid) return;
      ssePlanRef.current = updatedPlan;
      setPlan(updatedPlan);
    });

    return () => unsub();
  }, [active]);

  useEffect(() => {
    if (!active) return;
    const interval = setInterval(fetchPlan, 5000);
    return () => clearInterval(interval);
  }, [active, fetchPlan]);

  return { plan, loading, refresh: fetchPlan };
}
