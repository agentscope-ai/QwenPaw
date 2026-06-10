import type { PlanSnapshot } from "../task-graph/types";
import { fetchTasksSummary, subscribeDagEvents } from "../lib/api";
import { setCurrentPlan } from "../lib/plan-store";
import { toPlainJson } from "../lib/plain";
import { resolveBackendSessionId, getHostSessionApi } from "../lib/session-id";
import {
  TASK_CARD_STREAM_TOOL,
  type PlanToolStreamEvent,
} from "../lib/plan-tool-events";
import { resetNodeStreamEvents } from "../lib/node-stream-events";
import { isDatapawAgentSelected } from "../lib/agent";
import {
  saveTaskCardForSession,
  removeTaskCardForSession,
} from "../lib/task-card-storage";
import { isTaskGraphMessageId } from "../lib/pin-task-card";

export { TASK_GRAPH_MESSAGE_ID } from "../lib/task-card-storage";

type ChatRefHolder = {
  current: {
    messages?: {
      getMessages?: () => Array<{ id?: string }>;
      removeMessage?: (msg: { id: string }) => void;
    };
  } | null;
};

let chatRefHolder: ChatRefHolder = { current: null };
let activePlanId: string | null = null;
let injectInFlight = false;
let dagAbort: AbortController | null = null;
let dagSessionId: string | null = null;

/** Remove legacy task_graph messages still present in the chat stream. */
function purgeLegacyTaskGraphMessages(): void {
  const msgsApi = chatRefHolder.current?.messages;
  const getMessages = msgsApi?.getMessages;
  const removeMessage = msgsApi?.removeMessage;
  if (typeof getMessages === "function" && typeof removeMessage === "function") {
    for (const msg of getMessages()) {
      if (msg.id && isTaskGraphMessageId(msg.id)) {
        removeMessage({ id: msg.id });
      }
    }
  }

  const sessionApi = getHostSessionApi();
  const getPersistent = sessionApi?.getPersistentMessages as
    | (() => Array<{ id?: string }>)
    | undefined;
  const removePersistent = sessionApi?.removePersistentMessage as
    | ((id: string) => void)
    | undefined;
  if (typeof getPersistent === "function" && typeof removePersistent === "function") {
    for (const msg of getPersistent()) {
      if (msg.id && isTaskGraphMessageId(msg.id)) {
        removePersistent(msg.id);
      }
    }
  }
}

function stopDagEventsSubscription(): void {
  dagAbort?.abort();
  dagAbort = null;
  dagSessionId = null;
}

function ensureDagEventsSubscription(sessionId: string): void {
  if (!isDatapawAgentSelected()) return;
  const sid = resolveBackendSessionId(sessionId) || sessionId;
  if (!sid) return;
  if (dagSessionId === sid && dagAbort) return;

  stopDagEventsSubscription();
  dagSessionId = sid;
  dagAbort = new AbortController();

  void subscribeDagEvents(
    sid,
    "default",
    (plan) => {
      if (plan) applyCurrentPlan(plan, sid);
    },
    dagAbort.signal,
  ).catch(() => {
    /* DAG SSE is optional; plan updates follow create_plan + GET /api/tasks */
  });
}

function clearCurrentPlan(sessionId?: string | null): void {
  activePlanId = null;
  setCurrentPlan(null);
  const sid = resolveBackendSessionId(sessionId);
  if (sid) removeTaskCardForSession(sid);
}

function applyCurrentPlan(
  plan: PlanSnapshot,
  sessionId?: string | null,
): void {
  const plainPlan = toPlainJson(plan);
  const sid = resolveBackendSessionId(sessionId);
  const planChanged = Boolean(activePlanId && activePlanId !== plainPlan.id);
  console.info("[datapaw:task-card] applyCurrentPlan", {
    sessionId: sid,
    planId: plainPlan.id,
    planName: plainPlan.name,
    previousPlanId: activePlanId,
    planChanged,
  });

  if (planChanged) {
    resetNodeStreamEvents();
    clearCurrentPlan(sessionId);
  }

  activePlanId = plainPlan.id;
  setCurrentPlan(plainPlan);

  if (sid) {
    saveTaskCardForSession(sid, plainPlan);
    ensureDagEventsSubscription(sid);
  }

  purgeLegacyTaskGraphMessages();
}

export function installChatBridge(): void {
  const host = (
    window as {
      QwenPaw?: {
        host?: {
          chatBridge?: {
            setChatRef?: (ref: ChatRefHolder) => void;
            _ref?: ChatRefHolder;
          };
        };
      };
    }
  ).QwenPaw?.host;

  if (!host) return;
  if (!host.chatBridge) host.chatBridge = {};
  const bridge = host.chatBridge;

  const bindRef = (ref: ChatRefHolder) => {
    chatRefHolder = ref;
    purgeLegacyTaskGraphMessages();
  };

  bridge.setChatRef = bindRef;

  if (bridge._ref) {
    bindRef(bridge._ref);
  }
}

/** Manual refresh (plan correction) — fetches latest plan into plan-store. */
export async function refreshTaskCard(
  sessionId?: string | null,
): Promise<boolean> {
  const sid = resolveBackendSessionId(sessionId);
  console.info("[datapaw:task-card] refreshTaskCard", {
    inputSessionId: sessionId,
    resolvedSessionId: sid,
  });
  if (!sid) return false;
  return fetchAndApplyTaskPlan(sid);
}

async function fetchAndApplyTaskPlan(sessionId: string): Promise<boolean> {
  const summary = await fetchTasksSummary(sessionId);
  const plan = summary?.current_plan ?? null;
  if (!plan) return false;
  applyCurrentPlan(plan, sessionId);
  console.info(
    "[datapaw] Task plan updated:",
    plan.id,
    plan.name,
  );
  return true;
}

async function injectTaskPlanAfterCreatePlan(): Promise<void> {
  if (injectInFlight) {
    console.info("[datapaw:task-card] inject skipped: in flight");
    return;
  }

  const sessionId = resolveBackendSessionId();
  console.info("[datapaw:task-card] inject after create_plan", { sessionId });
  if (!sessionId) {
    console.warn("[datapaw] create_plan in stream but session id missing");
    return;
  }

  injectInFlight = true;
  try {
    let ok = await fetchAndApplyTaskPlan(sessionId);
    if (!ok) {
      await new Promise((resolve) => window.setTimeout(resolve, 600));
      ok = await fetchAndApplyTaskPlan(sessionId);
      if (!ok) {
        console.warn(
          "[datapaw] Tasks API returned no current_plan after create_plan in chat stream",
        );
      }
    }
  } catch (error) {
    console.warn("[datapaw] Failed to load task plan after create_plan:", error);
  } finally {
    injectInFlight = false;
  }
}

export function handlePlanToolInStream(event: PlanToolStreamEvent): void {
  console.info("[datapaw:task-card] plan tool event", event);
  if (!isDatapawAgentSelected()) return;
  if (event.name !== TASK_CARD_STREAM_TOOL) return;

  const schedule = (delayMs: number) => {
    window.setTimeout(() => {
      void injectTaskPlanAfterCreatePlan();
    }, delayMs);
  };

  if (event.phase === "result") {
    schedule(0);
    schedule(600);
  } else {
    schedule(400);
  }
}
