import {
  tasksApi,
  type HistoricalPlanSummary,
  type TasksSummaryResponse,
} from "../../../api/modules/tasks";
import type { PlanSnapshot } from "../components/TaskGraphPanel/types";

function getLatestHistoricalPlanId(
  plans: HistoricalPlanSummary[] | undefined,
): string | null {
  if (!plans?.length) return null;
  const sorted = [...plans].sort((a, b) => {
    const at = a.finished_at ? Date.parse(a.finished_at) : 0;
    const bt = b.finished_at ? Date.parse(b.finished_at) : 0;
    return bt - at;
  });
  return sorted[0]?.id || plans[plans.length - 1]?.id || null;
}

/** Active plan wins; after finish_plan falls back to the latest historical graph. */
export async function resolveTaskPlan(
  sessionId: string,
  userId: string,
  summary?: TasksSummaryResponse | null,
): Promise<PlanSnapshot | null> {
  const resolved =
    summary ?? (await tasksApi.getSummary(sessionId, userId).catch(() => null));
  if (!resolved) return null;

  if (resolved.current_plan) return resolved.current_plan;

  const historicalPlanId = getLatestHistoricalPlanId(resolved.historical_plans);
  if (!historicalPlanId) return null;

  try {
    const { plan } = await tasksApi.getHistoryPlan(
      sessionId,
      historicalPlanId,
      userId,
    );
    return plan ?? null;
  } catch {
    return null;
  }
}
