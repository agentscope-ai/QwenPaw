import type { PlanSnapshot } from "../task-graph/types";
import {
  fetchHistoricalTaskPlan,
  fetchTasksSummary,
  subscribeDagEvents,
  type TasksSummaryResponse,
} from "../lib/api";
import {
  clearStickyPlan,
  getDisplayPlans,
  setCurrentPlan,
  upsertHistoricalPlan,
} from "../lib/plan-store";
import { toPlainJson } from "../lib/plain";
import { resolveBackendSessionId, getHostSessionApi } from "../lib/session-id";
import {
  TASK_CARD_STREAM_TOOL,
  type PlanToolStreamEvent,
} from "../lib/plan-tool-events";
import { resetNodeStreamEvents } from "../lib/node-stream-events";
import { isDatapawAgentSelected } from "../lib/agent";
import {
  TASK_GRAPH_MESSAGE_ID,
  buildTaskCardMessage,
  clearTaskCardCurrentForSession,
  loadTaskCardPlans,
  saveTaskCardForSession,
  removeTaskCardForSession,
} from "../lib/task-card-storage";
import {
  isTaskGraphMessageId,
  schedulePinTaskCardDomToBottom,
  installTaskCardBottomPin,
} from "../lib/pin-task-card";

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
let chatSyncRetryTimer: ReturnType<typeof setTimeout> | null = null;
let chatSyncAttempts = 0;
const MAX_CHAT_SYNC_ATTEMPTS = 40;
let dagAbort: AbortController | null = null;
let dagSessionId: string | null = null;
let sessionSyncScheduled = false;
let lastSyncedSessionId: string | null = null;
let sessionSyncToken = 0;
let activePlanSourceSessionId: string | null = null;
const taskPlanSourceBySession = new Map<string, string>();

function logTaskGraphDebug(
  event: string,
  payload?: Record<string, unknown>,
): void {
  void event;
  void payload;
}

function pushTaskCardToLiveChat(
  message: ReturnType<typeof buildTaskCardMessage>,
): boolean {
  const msgsApi = chatRefHolder.current?.messages;
  const updateMessage = msgsApi?.updateMessage as
    | ((msg: Record<string, unknown> & { id: string }) => void)
    | undefined;
  if (typeof updateMessage !== "function") return false;

  updateMessage(message);
  schedulePinTaskCardDomToBottom();
  return true;
}

function scheduleTaskCardChatSync(
  message: ReturnType<typeof buildTaskCardMessage>,
): void {
  if (pushTaskCardToLiveChat(message)) {
    chatSyncAttempts = 0;
    if (chatSyncRetryTimer) {
      window.clearTimeout(chatSyncRetryTimer);
      chatSyncRetryTimer = null;
    }
    return;
  }

  if (chatSyncAttempts >= MAX_CHAT_SYNC_ATTEMPTS) return;
  chatSyncAttempts += 1;
  if (chatSyncRetryTimer) return;

  chatSyncRetryTimer = window.setTimeout(() => {
    chatSyncRetryTimer = null;
    scheduleTaskCardChatSync(message);
  }, 200);
}

function syncTaskCardMessage(): void {
  if (!isDatapawAgentSelected()) return;
  removeTaskCardFromChat();
}

/** Re-inject the current plan into chat after sessionApi patch or chat mount. */
export function resyncTaskCardFromPlanStore(): void {
  removeTaskCardFromChat();
}

function removeTaskCardFromChat(): void {
  const sessionApi = getHostSessionApi();
  const removePersistent = sessionApi?.removePersistentMessage as
    | ((id: string) => void)
    | undefined;
  if (typeof removePersistent === "function") {
    removePersistent(TASK_GRAPH_MESSAGE_ID);
  }

  const msgsApi = chatRefHolder.current?.messages;
  const removeMessage = msgsApi?.removeMessage;
  if (typeof removeMessage === "function") {
    removeMessage({ id: TASK_GRAPH_MESSAGE_ID });
  }
}

/** Remove duplicate legacy task_graph_* rows (keep the canonical datapaw_task_graph). */
function purgeLegacyTaskGraphMessages(): void {
  const msgsApi = chatRefHolder.current?.messages;
  const getMessages = msgsApi?.getMessages;
  const removeMessage = msgsApi?.removeMessage;
  if (typeof getMessages === "function" && typeof removeMessage === "function") {
    for (const msg of getMessages()) {
      if (
        msg.id &&
        msg.id !== TASK_GRAPH_MESSAGE_ID &&
        isTaskGraphMessageId(msg.id)
      ) {
        logTaskGraphDebug("purge-legacy-message", { messageId: msg.id });
        removeMessage({ id: msg.id });
      }
    }
  }
}

function syncPersistentTaskCard(plan: PlanSnapshot): void {
  logTaskGraphDebug("sync-persistent-task-card-skip", {
    planId: plan.id,
    planState: plan.state,
    anchorMessageId: plan.anchor_message_id ?? null,
  });
}

function stopDagEventsSubscription(): void {
  dagAbort?.abort();
  dagAbort = null;
  dagSessionId = null;
}

function ensureDagEventsSubscription(sessionId: string): void {
  if (!isDatapawAgentSelected()) return;
  const sid = sessionId || resolveBackendSessionId(sessionId);
  if (!sid) return;
  if (dagSessionId === sid && dagAbort) return;

  stopDagEventsSubscription();
  dagSessionId = sid;
  const abort = new AbortController();
  dagAbort = abort;

  void subscribeDagEvents(
    sid,
    "default",
    (plan) => {
      if (plan) {
        applyCurrentPlan(plan, sid);
        return;
      }
      // finish_plan archives the graph: current_plan becomes null in DAG SSE.
      logTaskGraphDebug("dag-current-plan-null", { sessionId: sid });
      void fetchAndApplyTaskPlan(sid);
    },
    abort.signal,
  )
    .catch(() => {
      /* DAG SSE is optional; plan updates follow create_plan + GET /api/tasks */
    })
    .finally(() => {
      if (dagAbort === abort) {
        dagAbort = null;
        dagSessionId = null;
      }
    });
}

function clearCurrentPlan(
  sessionId?: string | null,
  opts: { removeCache?: boolean } = { removeCache: true },
): void {
  const sid = resolveBackendSessionId(sessionId);
  activePlanId = null;
  clearStickyPlan(sid);
  activePlanSourceSessionId = null;
  stopDagEventsSubscription();
  logTaskGraphDebug("clear-current-plan", {
    sessionId: sid,
    removeCache: opts.removeCache !== false,
  });
  if (opts.removeCache !== false && sid) removeTaskCardForSession(sid);
  removeTaskCardFromChat();
}

function applyCurrentPlan(
  plan: PlanSnapshot,
  sessionId?: string | null,
  sourceSessionId?: string | null,
): void {
  const plainPlan = toPlainJson(plan);
  const sid = resolveBackendSessionId(sessionId);
  const sourceSid = sourceSessionId || sessionId || sid;

  logTaskGraphDebug("apply-current-plan", {
    sessionId: sid,
    sourceSessionId: sourceSid,
    planId: plainPlan.id,
    planState: plainPlan.state,
    anchorMessageId: plainPlan.anchor_message_id ?? null,
    previousPlanId: activePlanId,
  });

  activePlanId = plainPlan.id;
  activePlanSourceSessionId = sourceSid ?? null;
  setCurrentPlan(plainPlan, sourceSid ?? sid);

  const storageSessionIds = new Set(
    [sourceSid, sid, sessionId].filter(Boolean) as string[],
  );
  if (sourceSid) {
    for (const aliasSessionId of storageSessionIds) {
      taskPlanSourceBySession.set(aliasSessionId, sourceSid);
    }
  }
  for (const storageSessionId of storageSessionIds) {
    saveTaskCardForSession(storageSessionId, plainPlan, { current: true });
    logTaskGraphDebug("save-task-card-storage", {
      sessionId: storageSessionId,
      planId: plainPlan.id,
    });
  }

  if (sourceSid) {
    syncPersistentTaskCard(plainPlan);
    ensureDagEventsSubscription(sourceSid);
  }

  purgeLegacyTaskGraphMessages();
  syncTaskCardMessage();
}

function applyHistoricalPlan(
  plan: PlanSnapshot,
  sessionId?: string | null,
  sourceSessionId?: string | null,
): void {
  const plainPlan = toPlainJson(plan);
  const sid = resolveBackendSessionId(sessionId);
  const sourceSid = sourceSessionId || sessionId || sid;

  logTaskGraphDebug("apply-historical-plan", {
    sessionId: sid,
    sourceSessionId: sourceSid,
    planId: plainPlan.id,
    planState: plainPlan.state,
    anchorMessageId: plainPlan.anchor_message_id ?? null,
  });

  upsertHistoricalPlan(plainPlan, sourceSid ?? sid);

  const storageSessionIds = new Set(
    [sourceSid, sid, sessionId].filter(Boolean) as string[],
  );
  for (const storageSessionId of storageSessionIds) {
    saveTaskCardForSession(storageSessionId, plainPlan, { current: false });
  }
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
    resyncTaskCardFromPlanStore();
  };

  bridge.setChatRef = bindRef;
  installTaskCardBottomPin(() => chatRefHolder.current?.messages ?? null);

  if (bridge._ref) {
    bindRef(bridge._ref);
  }
}

/** Manual refresh (plan correction) — fetches latest plan into plan-store. */
export async function refreshTaskCard(
  sessionId?: string | null,
): Promise<boolean> {
  const sid = resolveBackendSessionId(sessionId);
  logTaskGraphDebug("refresh-task-card", {
    inputSessionId: sessionId ?? null,
    resolvedSessionId: sid,
  });
  if (!sid) return false;
  return fetchAndApplyTaskPlan(sid);
}

function getTaskPlanSessionCandidates(sessionId?: string | null): string[] {
  const baseIds = new Set<string>();
  if (sessionId) baseIds.add(sessionId);
  const resolved = resolveBackendSessionId(sessionId);
  if (resolved) baseIds.add(resolved);
  const current = (window as Window & { currentSessionId?: string })
    .currentSessionId;
  if (current) baseIds.add(current);

  const ids = new Set(baseIds);
  for (const baseId of baseIds) {
    const sourceId = taskPlanSourceBySession.get(baseId);
    if (sourceId) ids.add(sourceId);
  }
  return [...ids];
}

async function fetchAndApplyTaskPlan(sessionId: string): Promise<boolean> {
  const candidates = getTaskPlanSessionCandidates(sessionId);
  logTaskGraphDebug("fetch-apply-task-plan-start", {
    requestedSessionId: sessionId,
    candidates,
    activePlanId,
  });
  for (const candidateSessionId of candidates) {
    const summary = await fetchTasksSummary(candidateSessionId);
    const plans = await resolvePlansFromSummary(candidateSessionId, summary);
    logTaskGraphDebug("tasks-summary", {
      requestedSessionId: sessionId,
      sessionId: candidateSessionId,
      candidates,
      hasCurrentPlan: Boolean(summary?.current_plan),
      historicalCount: summary?.historical_plans?.length ?? 0,
      resolvedPlanIds: plans.map((plan) => plan.id),
      resolvedPlans: plans.map((plan) => ({
        id: plan.id,
        state: plan.state,
        anchorMessageId: plan.anchor_message_id ?? null,
      })),
    });
    if (!plans.length) continue;
    const retainedCurrentPlanId = summary?.current_plan?.id ?? null;
    logTaskGraphDebug("apply-task-plans", {
      requestedSessionId: sessionId,
      sourceSessionId: candidateSessionId,
      retainedCurrentPlanId,
      planIds: plans.map((plan) => plan.id),
    });
    if (!retainedCurrentPlanId) {
      activePlanId = null;
      setCurrentPlan(null, candidateSessionId);
      const storageSessionIds = new Set(
        [candidateSessionId, sessionId].filter(Boolean) as string[],
      );
      for (const storageSessionId of storageSessionIds) {
        clearTaskCardCurrentForSession(storageSessionId);
      }
    }
    for (const plan of plans) {
      if (retainedCurrentPlanId && retainedCurrentPlanId === plan.id) {
        applyCurrentPlan(plan, sessionId, candidateSessionId);
      } else {
        applyHistoricalPlan(plan, sessionId, candidateSessionId);
      }
    }
    return true;
  }
  logTaskGraphDebug("fetch-apply-task-plan-empty", {
    requestedSessionId: sessionId,
    candidates,
  });
  return false;
}

function getLatestHistoricalPlanId(
  summary: TasksSummaryResponse | null,
): string | null {
  const plans = summary?.historical_plans ?? [];
  if (!plans.length) return null;
  const sorted = [...plans].sort((a, b) => {
    const at = a.finished_at ? Date.parse(a.finished_at) : 0;
    const bt = b.finished_at ? Date.parse(b.finished_at) : 0;
    return bt - at;
  });
  return sorted[0]?.id || plans[plans.length - 1]?.id || null;
}

async function resolvePlansFromSummary(
  sessionId: string,
  summary: TasksSummaryResponse | null,
): Promise<PlanSnapshot[]> {
  const plans: PlanSnapshot[] = [];
  const seen = new Set<string>();
  if (summary?.current_plan) {
    plans.push(summary.current_plan);
    seen.add(summary.current_plan.id);
  }

  const historicalIds = (summary?.historical_plans ?? [])
    .map((historical) => historical.id)
    .filter((id) => id && !seen.has(id));
  logTaskGraphDebug("resolve-plans-from-summary", {
    sessionId,
    currentPlanId: summary?.current_plan?.id ?? null,
    historicalIds,
  });
  const historicalPlans = await Promise.all(
    historicalIds.map((planId) => fetchHistoricalTaskPlan(sessionId, planId)),
  );
  logTaskGraphDebug("resolve-historical-plans-result", {
    sessionId,
    requestedHistoricalIds: historicalIds,
    returnedHistoricalIds: historicalPlans
      .filter(Boolean)
      .map((plan) => plan?.id),
  });
  for (const plan of historicalPlans) {
    if (!plan || seen.has(plan.id)) continue;
    plans.push(plan);
    seen.add(plan.id);
  }

  if (!plans.length) {
    const historicalPlanId = getLatestHistoricalPlanId(summary);
    if (historicalPlanId) {
      const plan = await fetchHistoricalTaskPlan(sessionId, historicalPlanId);
      if (plan) plans.push(plan);
    }
  }
  return plans;
}

async function syncTaskPlanForCurrentSession(sessionId: string): Promise<void> {
  const token = ++sessionSyncToken;
  logTaskGraphDebug("sync-session-plan-start", { sessionId, token });

  try {
    if (token !== sessionSyncToken || lastSyncedSessionId !== sessionId) {
      logTaskGraphDebug("sync-session-plan-stale", {
        sessionId,
        token,
        currentToken: sessionSyncToken,
        lastSyncedSessionId,
      });
      return;
    }

    const ok = await fetchAndApplyTaskPlan(sessionId);
    logTaskGraphDebug("sync-session-plan-result", {
      sessionId,
      synced: ok,
      activePlanId,
      activePlanSourceSessionId,
    });
    if (ok) return;

    const cachedPlans = loadTaskCardPlans(sessionId);
    if (cachedPlans.length) {
      const currentCached = cachedPlans.find((item) => item.current)?.plan ?? null;
      logTaskGraphDebug("sync-session-plan-cache-hit", {
        sessionId,
        planIds: cachedPlans.map((item) => item.plan.id),
        currentPlanId: currentCached?.id ?? null,
      });
      for (const item of cachedPlans) {
        if (currentCached && item.plan.id === currentCached.id) {
          applyCurrentPlan(item.plan, sessionId);
        } else {
          applyHistoricalPlan(item.plan, sessionId);
        }
      }
      return;
    }
    if (getDisplayPlans().length) {
      return;
    }
    clearCurrentPlan(sessionId, { removeCache: false });
  } catch (error) {
    if (token === sessionSyncToken) {
      console.warn("[datapaw] Failed to sync task plan for session:", error);
    }
  }
}

function getCurrentBackendSessionId(): string | null {
  return resolveBackendSessionId();
}

/**
 * Sync the task graph when the selected chat session changes.
 * This restores historical sessions from the backend, without showing stale
 * localStorage plans in a fresh session.
 */
export function scheduleSessionTaskPlanSync(): void {
  if (sessionSyncScheduled) return;
  sessionSyncScheduled = true;

  const sync = () => {
    if (!isDatapawAgentSelected()) {
      if (lastSyncedSessionId || activePlanId) {
        lastSyncedSessionId = null;
        clearCurrentPlan(null, { removeCache: false });
      }
      logTaskGraphDebug("schedule-session-sync-skip", {
        reason: "agent-not-selected",
      });
      return;
    }

    const sessionId = getCurrentBackendSessionId();
    if (!sessionId || sessionId === lastSyncedSessionId) {
      if (sessionId === lastSyncedSessionId) return;
      logTaskGraphDebug("schedule-session-sync-skip", {
        reason: "missing-session",
        sessionId,
        lastSyncedSessionId,
      });
      return;
    }

    lastSyncedSessionId = sessionId;
    activePlanId = null;
    resetNodeStreamEvents();
    purgeLegacyTaskGraphMessages();
    logTaskGraphDebug("schedule-session-sync", { sessionId });
    void syncTaskPlanForCurrentSession(sessionId);
  };

  sync();
  window.setInterval(sync, 300);
}

async function injectTaskPlanAfterCreatePlan(): Promise<void> {
  if (injectInFlight) {
    logTaskGraphDebug("inject-after-create-plan-skip", { reason: "in-flight" });
    return;
  }

  const sessionId = resolveBackendSessionId();
  logTaskGraphDebug("inject-after-create-plan-start", { sessionId });
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
    logTaskGraphDebug("inject-after-create-plan-finish", { sessionId });
  }
}

export function handlePlanToolInStream(event: PlanToolStreamEvent): void {
  logTaskGraphDebug("plan-tool-stream-event", {
    name: event.name,
    phase: event.phase,
  });
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
