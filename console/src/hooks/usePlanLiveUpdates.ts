import { useCallback, useEffect, useState } from "react";
import api from "../api";
import { subscribePlanUpdates } from "../api/modules/plan";
import type { Plan } from "../api/types";

/**
 * Subscribe to plan config + SSE while the chat page is active so the Plan
 * drawer stays in sync even when closed (same agent session).
 *
 * @param selectedAgent When this changes, SSE is torn down and recreated so
 *   requests use the correct ``X-Agent-Id`` for the active profile.
 */
export function usePlanLiveUpdates(
  chatPageActive: boolean,
  selectedAgent: string,
  sessionScope: string,
) {
  const [planEnabled, setPlanEnabled] = useState<boolean | null>(null);
  const [livePlan, setLivePlan] = useState<Plan | null | undefined>(undefined);

  const refresh = useCallback(() => {
    api
      .getPlanConfig()
      .then((cfg) => setPlanEnabled(cfg.enabled))
      .catch(() => setPlanEnabled(false));
    api
      .getCurrentPlan()
      .then(setLivePlan)
      .catch(() => setLivePlan(null));
  }, [selectedAgent]);

  useEffect(() => {
    if (!chatPageActive) {
      setPlanEnabled(null);
      return;
    }
    refresh();
  }, [chatPageActive, selectedAgent, refresh, sessionScope]);

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
  }, [chatPageActive, planEnabled, selectedAgent, sessionScope]);

  return { livePlan, planEnabled, refresh };
}
