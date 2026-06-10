import { isDatapawAgentSelected } from "../../../host-chat/fetch-patch";
import { resolveBackendSessionId } from "../components/ChatSenderToolbar/utils";
import {
  isTaskCardRefreshTool,
  type PlanToolStreamEvent,
} from "./planToolStream";

let refreshInFlight = false;

async function refreshViaTaskCardModule(
  sessionId?: string | null,
): Promise<boolean> {
  const { refreshTaskCard } = await import(
    "../../../../../ui/src/patches/task-card"
  );
  return refreshTaskCard(sessionId);
}

export async function refreshTaskCardFromTasksApi(
  sessionId?: string | null,
): Promise<boolean> {
  if (!isDatapawAgentSelected()) return false;

  const sid = resolveBackendSessionId(sessionId);
  if (!sid) return false;

  if (refreshInFlight) return false;
  refreshInFlight = true;
  try {
    let ok = await refreshViaTaskCardModule(sid);
    if (!ok) {
      await new Promise((resolve) => window.setTimeout(resolve, 600));
      ok = await refreshViaTaskCardModule(sid);
    }
    return ok;
  } finally {
    refreshInFlight = false;
  }
}

/** Chat SSE plan/graph tool — refresh card in message stream via GET /api/tasks. */
export function handlePlanToolStreamRefresh(event: PlanToolStreamEvent): void {
  if (!isDatapawAgentSelected()) return;
  if (!isTaskCardRefreshTool(event.name)) return;

  const schedule = (delayMs: number) => {
    window.setTimeout(() => {
      void refreshTaskCardFromTasksApi();
    }, delayMs);
  };

  if (event.phase === "result") {
    schedule(0);
    schedule(600);
  } else {
    schedule(400);
  }
}
