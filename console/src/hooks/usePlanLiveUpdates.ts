import { useCallback, useEffect, useState } from "react";
import api from "../api";
import { subscribePlanUpdates } from "../api/modules/plan";
import type { Plan } from "../api/types";

/**
 * Subscribe to plan config + SSE while the chat page is active so the Plan
 * drawer stays in sync even when closed (same agent session).
 */
export function usePlanLiveUpdates(chatPageActive: boolean) {
  const [planEnabled, setPlanEnabled] = useState<boolean | null>(null);
  const [livePlan, setLivePlan] = useState<Plan | null>(null);

  const refresh = useCallback(() => {
    api
      .getPlanConfig()
      .then((cfg) => setPlanEnabled(cfg.enabled))
      .catch(() => setPlanEnabled(false));
    api
      .getCurrentPlan()
      .then(setLivePlan)
      .catch(() => setLivePlan(null));
  }, []);

  useEffect(() => {
    if (!chatPageActive) {
      setPlanEnabled(null);
      return;
    }
    refresh();
  }, [chatPageActive, refresh]);

  useEffect(() => {
    if (!chatPageActive || !planEnabled) return;
    let unsub: (() => void) | undefined;
    let cancelled = false;
    subscribePlanUpdates((updated) => setLivePlan(updated))
      .then((close) => {
        if (cancelled) {
          close();
        } else {
          unsub = close;
        }
      })
      .catch(() => {
        /* same as PlanPanel */
      });
    return () => {
      cancelled = true;
      unsub?.();
    };
  }, [chatPageActive, planEnabled]);

  return { livePlan, planEnabled, refresh };
}
