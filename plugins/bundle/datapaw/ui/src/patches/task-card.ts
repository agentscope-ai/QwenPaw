import type { PlanSnapshot } from "../task-graph/types";
import { fetchTasksSummary, subscribeDagEvents } from "../lib/api";
import { setCurrentPlan } from "../lib/plan-store";
import { toPlainJson } from "../lib/plain";
import { resolveBackendSessionId, getHostSessionApi } from "../lib/session-id";
import {
  TASK_CARD_REFRESH_TOOLS,
  type PlanToolStreamEvent,
} from "../lib/plan-tool-events";
import { resetNodeStreamEvents } from "../lib/node-stream-events";
import { detectLang } from "../lib/lang";
import { isDatapawAgentSelected } from "../lib/agent";
import {
  TASK_GRAPH_MESSAGE_ID,
  buildTaskCardMessage,
  saveTaskCardForSession,
  loadTaskCardPlan,
} from "../lib/task-card-storage";

export { TASK_GRAPH_MESSAGE_ID };

type ChatRefHolder = {
  current: {
    messages?: {
      updateMessage?: (msg: Record<string, unknown>) => void;
      removeMessage?: (msg: { id: string }) => void;
    };
  } | null;
};

let chatRefHolder: ChatRefHolder = { current: null };
const confirmedSessions = new Set<string>();
let activePlanId: string | null = null;
let injectDebounceTimer: ReturnType<typeof setTimeout> | null = null;
let injectInFlight = false;
let restoreScheduled = false;
let dagAbort: AbortController | null = null;
let dagSessionId: string | null = null;

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
      if (plan) upsertTaskCard(plan, sid);
    },
    dagAbort.signal,
  ).catch(() => {
    /* DAG SSE is optional; GET /api/tasks still works */
  });
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

  bridge.setChatRef = (ref: ChatRefHolder) => {
    chatRefHolder = ref;
    void tryRestoreTaskCardOnLoad();
  };

  if (bridge._ref) {
    chatRefHolder = bridge._ref;
    void tryRestoreTaskCardOnLoad();
  }
}

function isTaskGraphMessageId(id: unknown): boolean {
  return (
    typeof id === "string" &&
    (id === TASK_GRAPH_MESSAGE_ID || id.startsWith("task_graph_"))
  );
}

function removeTaskGraphCardById(msgId: string): void {
  const sessionApi = getHostSessionApi();
  const removePersistent = sessionApi?.removePersistentMessage;
  if (typeof removePersistent === "function") {
    removePersistent.call(sessionApi, msgId);
  }
  chatRefHolder.current?.messages?.removeMessage?.({ id: msgId });
}

function removeAllTaskGraphCards(): void {
  removeTaskGraphCardById(TASK_GRAPH_MESSAGE_ID);
  if (activePlanId) {
    removeTaskGraphCardById(`task_graph_${activePlanId}`);
  }

  const sessionApi = getHostSessionApi();
  const getPersistent = sessionApi?.getPersistentMessages;
  if (typeof getPersistent === "function") {
    const msgs = getPersistent.call(sessionApi) as Array<{ id?: string }>;
    for (const msg of msgs) {
      if (msg.id && isTaskGraphMessageId(msg.id)) {
        removeTaskGraphCardById(msg.id);
      }
    }
  }
}

function upsertTaskCard(plan: PlanSnapshot, sessionId?: string | null): void {
  const plainPlan = toPlainJson(plan);
  const sid = resolveBackendSessionId(sessionId);
  const planChanged = Boolean(activePlanId && activePlanId !== plainPlan.id);

  if (planChanged) {
    removeTaskGraphCardById(`task_graph_${activePlanId}`);
    resetNodeStreamEvents();
    removeAllTaskGraphCards();
  } else if (!activePlanId) {
    removeAllTaskGraphCards();
  }

  activePlanId = plainPlan.id;
  setCurrentPlan(plainPlan);

  const cardMsg = buildTaskCardMessage(plainPlan);
  if (sid) {
    saveTaskCardForSession(sid, plainPlan);
    ensureDagEventsSubscription(sid);
  }

  const sessionApi = getHostSessionApi();
  const setPersistent = sessionApi?.setPersistentMessage;
  if (typeof setPersistent === "function") {
    setPersistent.call(sessionApi, cardMsg);
  }

  chatRefHolder.current?.messages?.updateMessage?.(cardMsg);
}

function confirmLoadTaskCard(event: PlanToolStreamEvent): boolean {
  const lang = detectLang();
  const title =
    lang === "zh"
      ? `检测到 ${event.name}（${event.phase}）`
      : `Detected ${event.name} (${event.phase})`;
  const message =
    lang === "zh"
      ? "是否加载任务计划卡片？将调用 /api/tasks 接口获取当前 DAG。"
      : "Load the task plan card? This will call GET /api/tasks for the current DAG.";
  return window.confirm(`${title}\n\n${message}`);
}

export async function refreshTaskCard(
  sessionId?: string | null,
): Promise<boolean> {
  const sid = resolveBackendSessionId(sessionId);
  if (!sid) return false;
  return fetchAndInjectTaskCard(sid);
}

async function fetchAndInjectTaskCard(sessionId: string): Promise<boolean> {
  const summary = await fetchTasksSummary(sessionId);
  const plan = summary?.current_plan ?? null;
  if (!plan) return false;
  upsertTaskCard(plan, sessionId);
  console.info("[datapaw] Task card injected:", plan.id, plan.name);
  return true;
}

async function restoreFromCache(sessionId: string): Promise<boolean> {
  const cached = loadTaskCardPlan(sessionId);
  if (!cached) return false;
  upsertTaskCard(cached, sessionId);
  console.info("[datapaw] Task card restored from cache:", cached.id);
  return true;
}

export async function tryRestoreTaskCardOnLoad(): Promise<boolean> {
  if (!isDatapawAgentSelected()) return true;

  const sessionId = resolveBackendSessionId();
  if (!sessionId) return false;

  try {
    const ok = await fetchAndInjectTaskCard(sessionId);
    if (ok) return true;
    return restoreFromCache(sessionId);
  } catch (error) {
    console.warn("[datapaw] Failed to restore task card:", error);
    return restoreFromCache(sessionId);
  }
}

export function scheduleTaskCardRestore(): void {
  if (restoreScheduled) return;
  restoreScheduled = true;

  let attempts = 0;
  const timer = window.setInterval(() => {
    attempts += 1;
    void tryRestoreTaskCardOnLoad().then((done) => {
      if (done || attempts >= 150) {
        window.clearInterval(timer);
      }
    });
  }, 200);
}

async function injectTaskCardFromStream(
  event: PlanToolStreamEvent,
  skipConfirm = false,
): Promise<void> {
  if (injectInFlight) return;

  const sessionId = resolveBackendSessionId();
  if (!sessionId) {
    console.warn("[datapaw] plan tool in stream but session id missing");
    return;
  }

  const confirmKey = `${sessionId}:${event.name}`;
  if (!skipConfirm && !confirmedSessions.has(confirmKey)) {
    if (!confirmLoadTaskCard(event)) {
      console.info("[datapaw] User declined task card load");
      return;
    }
    confirmedSessions.add(confirmKey);
  }

  injectInFlight = true;
  try {
    let ok = await fetchAndInjectTaskCard(sessionId);
    if (!ok) {
      await new Promise((resolve) => window.setTimeout(resolve, 600));
      ok = await fetchAndInjectTaskCard(sessionId);
      if (!ok) {
        ok = await restoreFromCache(sessionId);
      }
      if (!ok) {
        const lang = detectLang();
        window.alert(
          lang === "zh"
            ? "任务接口未返回 current_plan，请稍后重试。"
            : "Tasks API returned no current_plan. Try again shortly.",
        );
      }
    }
  } catch (error) {
    console.warn("[datapaw] Failed to load task card:", error);
  } finally {
    injectInFlight = false;
  }
}

export function handlePlanToolInStream(event: PlanToolStreamEvent): void {
  if (!isDatapawAgentSelected()) return;
  if (!TASK_CARD_REFRESH_TOOLS.has(event.name)) return;
  if (event.phase !== "result") return;

  if (injectDebounceTimer) {
    window.clearTimeout(injectDebounceTimer);
  }
  injectDebounceTimer = window.setTimeout(() => {
    injectDebounceTimer = null;
    const sessionId = resolveBackendSessionId();
    const skipConfirm =
      event.name === "create_plan" ||
      event.name === "finish_plan" ||
      (sessionId
        ? confirmedSessions.has(`${sessionId}:${event.name}`)
        : false);
    void injectTaskCardFromStream(event, skipConfirm);
  }, 200);
}
