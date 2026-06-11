import type { PlanSnapshot } from "../task-graph/types";
import {
  fetchHistoricalTaskPlan,
  fetchTasksSummary,
  subscribeDagEvents,
  type TasksSummaryResponse,
} from "../lib/api";
import {
  clearStickyPlan,
  getDisplayPlan,
  setCurrentPlan,
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
  loadTaskCardPlan,
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
  console.info("[datapaw:task-graph-debug]", event, payload ?? {});
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

function syncTaskCardMessage(plan: PlanSnapshot): void {
  if (!isDatapawAgentSelected()) return;
  removeTaskCardFromChat();
  console.info("[datapaw:task-card] cleared persistent task card message", {
    planId: plan.id,
    messageId: TASK_GRAPH_MESSAGE_ID,
  });
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
  dagAbort = new AbortController();

  void subscribeDagEvents(
    sid,
    "default",
    (plan) => {
      if (plan) {
        applyCurrentPlan(plan, sid);
        return;
      }
      // finish_plan archives the graph: current_plan becomes null in DAG SSE.
      void fetchAndApplyTaskPlan(sid);
    },
    dagAbort.signal,
  ).catch(() => {
    /* DAG SSE is optional; plan updates follow create_plan + GET /api/tasks */
  });
}

function clearCurrentPlan(
  sessionId?: string | null,
  opts: { removeCache?: boolean } = { removeCache: true },
): void {
  const sid = resolveBackendSessionId(sessionId);
  activePlanId = null;
  clearStickyPlan();
  setCurrentPlan(null);
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
  const planChanged = Boolean(activePlanId && activePlanId !== plainPlan.id);

  logTaskGraphDebug("apply-current-plan", {
    sessionId: sid,
    sourceSessionId: sourceSid,
    planId: plainPlan.id,
    planState: plainPlan.state,
    anchorMessageId: plainPlan.anchor_message_id ?? null,
    previousPlanId: activePlanId,
    planChanged,
  });

  if (planChanged) {
    resetNodeStreamEvents();
    clearCurrentPlan(sessionId);
  }

  activePlanId = plainPlan.id;
  activePlanSourceSessionId = sourceSid ?? null;
  setCurrentPlan(plainPlan);

  const storageSessionIds = new Set(
    [sourceSid, sid, sessionId].filter(Boolean) as string[],
  );
  if (sourceSid) {
    for (const aliasSessionId of storageSessionIds) {
      taskPlanSourceBySession.set(aliasSessionId, sourceSid);
    }
  }
  for (const storageSessionId of storageSessionIds) {
    saveTaskCardForSession(storageSessionId, plainPlan);
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
  syncTaskCardMessage(plainPlan);
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
  for (const candidateSessionId of candidates) {
    const summary = await fetchTasksSummary(candidateSessionId);
    const plan = await resolvePlanFromSummary(candidateSessionId, summary);
    logTaskGraphDebug("tasks-summary", {
      requestedSessionId: sessionId,
      sessionId: candidateSessionId,
      candidates,
      hasCurrentPlan: Boolean(summary?.current_plan),
      historicalCount: summary?.historical_plans?.length ?? 0,
      resolvedPlanId: plan?.id ?? null,
      resolvedPlanState: plan?.state ?? null,
    });
    if (!plan) continue;
    applyCurrentPlan(plan, sessionId, candidateSessionId);
    return true;
  }
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

async function resolvePlanFromSummary(
  sessionId: string,
  summary: TasksSummaryResponse | null,
): Promise<PlanSnapshot | null> {
  if (summary?.current_plan) return summary.current_plan;
  const historicalPlanId = getLatestHistoricalPlanId(summary);
  if (!historicalPlanId) return null;
  return fetchHistoricalTaskPlan(sessionId, historicalPlanId);
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

    const cached = loadTaskCardPlan(sessionId);
    if (cached) {
      logTaskGraphDebug("sync-session-plan-cache-hit", {
        sessionId,
        planId: cached.id,
        planState: cached.state,
      });
      applyCurrentPlan(cached, sessionId);
      return;
    }
    if (getDisplayPlan()) {
      console.info("[datapaw:task-card] keep sticky plan after empty summary", {
        sessionId,
        planId: getDisplayPlan()?.id,
      });
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
      return;
    }

    const sessionId = getCurrentBackendSessionId();
    if (!sessionId || sessionId === lastSyncedSessionId) return;

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
