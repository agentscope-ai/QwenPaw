/**
 * Watches offloaded tool calls via ToolStream SSE (+ polling fallback).
 * Updates backgroundTasksStore with liveOutput and final status/result.
 */

import { message } from "antd";
import i18n from "../i18n";
import {
  extractOutputText,
  subscribeToolCallStream,
  toolCallsApi,
} from "../api/modules/toolCalls";
import { useBackgroundTasksStore } from "../stores/backgroundTasksStore";
import { resolveBackendSessionId } from "../utils/resolveBackendSessionId";

const POLL_INTERVAL_MS = 3000;
const LIVE_OUTPUT_MAX = 80_000;

type AbortFn = () => void;

const activeWatchers = new Map<string, AbortFn>();
const finalizedIds = new Set<string>();

function chunkToText(payload: unknown): string {
  if (!payload || typeof payload !== "object") return "";
  const p = payload as { data?: unknown; type?: string };
  const data = p.data;
  if (data == null) return "";
  if (typeof data === "string") return data;
  if (typeof data === "object") {
    const d = data as Record<string, unknown>;
    if (typeof d.text === "string") return d.text;
    if (typeof d.content === "string") return d.content;
    // ToolChunk / ToolResponse-like: content may be array of blocks
    if (Array.isArray(d.content)) {
      return d.content
        .map((b) =>
          b &&
          typeof b === "object" &&
          typeof (b as { text?: string }).text === "string"
            ? (b as { text: string }).text
            : "",
        )
        .filter(Boolean)
        .join("");
    }
    try {
      return JSON.stringify(data);
    } catch {
      return "";
    }
  }
  return String(data);
}

async function finalizeFromOutput(
  sessionId: string,
  toolCallId: string,
  fallbackLive: string,
  cancelled: boolean,
): Promise<void> {
  if (finalizedIds.has(toolCallId)) return;
  finalizedIds.add(toolCallId);

  const store = useBackgroundTasksStore.getState();
  let resultText = fallbackLive;
  let status: "done" | "cancelled" = cancelled ? "cancelled" : "done";

  try {
    const output = await toolCallsApi.getOutput(sessionId, toolCallId);
    const extracted = extractOutputText(output);
    if (extracted) resultText = extracted;
    if (
      output.final_state === "interrupted" ||
      output.final_state === "cancelled"
    ) {
      status = "cancelled";
    }
  } catch {
    // Cache miss / race — keep liveOutput
  }

  if (resultText.length > LIVE_OUTPUT_MAX) {
    resultText = resultText.slice(resultText.length - LIVE_OUTPUT_MAX);
  }

  const task = store.tasks.find((t) => t.toolCallId === toolCallId);
  // Skip toast if already terminal (e.g. user cancelled from panel)
  const alreadyTerminal =
    task?.status === "done" || task?.status === "cancelled";

  store.updateTask(toolCallId, {
    status,
    result: resultText || null,
    hintVisible: true,
  });

  if (alreadyTerminal) return;

  const toolName = task?.toolName || toolCallId;
  if (status === "cancelled") {
    message.info(
      i18n.t("tool.control.toast.bgCancelled", {
        tool: toolName,
        defaultValue: `Background tool cancelled: ${toolName}`,
      }),
    );
  } else {
    message.success(
      i18n.t("tool.control.toast.bgComplete", {
        tool: toolName,
        defaultValue: `Background tool complete: ${toolName}`,
      }),
    );
  }
}

function startPolling(sessionId: string, toolCallId: string): AbortFn {
  let stopped = false;
  const timer = setInterval(async () => {
    if (stopped) return;
    const finishPoll = async (cancelled: boolean) => {
      if (stopped) return;
      stopped = true;
      clearInterval(timer);
      const abort = activeWatchers.get(toolCallId);
      activeWatchers.delete(toolCallId);
      // Abort stream leg only; poll already stopped
      abort?.();
      const live =
        useBackgroundTasksStore
          .getState()
          .tasks.find((t) => t.toolCallId === toolCallId)?.liveOutput || "";
      await finalizeFromOutput(sessionId, toolCallId, live, cancelled);
    };
    try {
      const info = await toolCallsApi.getInfo(sessionId, toolCallId);
      if (info.status === "running" || info.status === "offloaded") {
        return;
      }
      const cancelled =
        info.end_state === "interrupted" || !!info.force_cancelled;
      await finishPoll(cancelled);
    } catch {
      // 404 after finalize — treat as completed and try getOutput once
      await finishPoll(false);
    }
  }, POLL_INTERVAL_MS);

  return () => {
    stopped = true;
    clearInterval(timer);
  };
}

/**
 * Register a task in the background queue and start the SSE/poll watcher.
 * Idempotent: safe for both manual offload and system auto-offload.
 *
 * sessionId may be empty on the first turn before window.currentSessionId is
 * set — we still enqueue the task (panel shows it) and resolve session later
 * for the watcher from window when possible.
 */
export function registerBackgroundTask(opts: {
  sessionId: string;
  toolCallId: string;
  toolName: string;
  startTime?: number;
  /** When true, skip SSE and hydrate /output immediately (fast bg finish). */
  alreadyCompleted?: boolean;
}): void {
  const {
    toolCallId,
    toolName,
    startTime = Date.now(),
    alreadyCompleted = false,
  } = opts;
  if (!toolCallId) return;

  const resolvedSessionId = resolveBackendSessionId(opts.sessionId);

  useBackgroundTasksStore.getState().addTask({
    toolCallId,
    toolName: toolName || toolCallId,
    sessionId: resolvedSessionId,
    startTime,
  });

  const backfillSessionId = (sid: string) => {
    useBackgroundTasksStore.setState((state) => ({
      tasks: state.tasks.map((t) =>
        t.toolCallId === toolCallId && !t.sessionId
          ? { ...t, sessionId: sid }
          : t,
      ),
    }));
  };

  if (alreadyCompleted) {
    const hydrate = (sid: string) => {
      if (!sid) return false;
      backfillSessionId(sid);
      void finalizeFromOutput(sid, toolCallId, "", false);
      return true;
    };
    if (!hydrate(resolvedSessionId)) {
      let attempts = 0;
      const timer = setInterval(() => {
        attempts += 1;
        const sid = resolveBackendSessionId();
        if (hydrate(sid) || attempts >= 20) {
          clearInterval(timer);
        }
      }, 250);
    }
    return;
  }

  // Watcher needs a session id for API paths; retry briefly if still empty.
  const startWatcher = (sid: string) => {
    if (!sid) return false;
    startBackgroundTaskWatcher(sid, toolCallId);
    // Back-fill sessionId on the task if it was empty at enqueue time.
    backfillSessionId(sid);
    return true;
  };

  if (!startWatcher(resolvedSessionId)) {
    let attempts = 0;
    const timer = setInterval(() => {
      attempts += 1;
      const sid = resolveBackendSessionId();
      if (startWatcher(sid) || attempts >= 20) {
        clearInterval(timer);
      }
    }, 250);
  }
}

/**
 * Start watching an offloaded tool call. Idempotent per toolCallId.
 */
export function startBackgroundTaskWatcher(
  sessionId: string,
  toolCallId: string,
): void {
  if (activeWatchers.has(toolCallId) || finalizedIds.has(toolCallId)) return;

  let settled = false;
  let pollAbort: AbortFn | null = null;
  let streamAbort: AbortFn = () => {};

  const abortAll = () => {
    streamAbort();
    pollAbort?.();
  };

  const settle = async (cancelled: boolean) => {
    if (settled) return;
    settled = true;
    activeWatchers.delete(toolCallId);
    abortAll();
    const live =
      useBackgroundTasksStore
        .getState()
        .tasks.find((t) => t.toolCallId === toolCallId)?.liveOutput || "";
    await finalizeFromOutput(sessionId, toolCallId, live, cancelled);
  };

  streamAbort = subscribeToolCallStream(sessionId, toolCallId, {
    onChunk: (payload) => {
      const text = chunkToText(payload);
      if (text) {
        useBackgroundTasksStore.getState().appendLiveOutput(toolCallId, text);
      }
    },
    onDone: () => {
      void settle(false);
    },
    onError: () => {
      if (settled || pollAbort) return;
      pollAbort = startPolling(sessionId, toolCallId);
    },
  });

  activeWatchers.set(toolCallId, abortAll);
}

/** Stop watcher without changing task status (e.g. user removed row). */
export function stopBackgroundTaskWatcher(toolCallId: string): void {
  const abort = activeWatchers.get(toolCallId);
  if (abort) {
    abort();
    activeWatchers.delete(toolCallId);
  }
}

/**
 * User cancelled from panel: stop stream, call cancel API, update store.
 * On API failure, resume the watcher so the task is not orphaned.
 */
export async function cancelBackgroundTask(
  sessionId: string,
  toolCallId: string,
): Promise<void> {
  const sid = (sessionId || "").trim();
  if (!sid) {
    message.error(
      i18n.t(
        "chat.backgroundTasks.cancelFailed",
        "Failed to cancel background task",
      ),
    );
    throw new Error("Missing backend session id for cancel");
  }
  stopBackgroundTaskWatcher(toolCallId);
  try {
    await toolCallsApi.cancel(sid, toolCallId);
  } catch (err) {
    finalizedIds.delete(toolCallId);
    startBackgroundTaskWatcher(sid, toolCallId);
    message.error(
      i18n.t(
        "chat.backgroundTasks.cancelFailed",
        "Failed to cancel background task",
      ),
    );
    throw err;
  }
  finalizedIds.add(toolCallId);
  const live =
    useBackgroundTasksStore
      .getState()
      .tasks.find((t) => t.toolCallId === toolCallId)?.liveOutput || "";
  useBackgroundTasksStore.getState().updateTask(toolCallId, {
    status: "cancelled",
    result: live || null,
    hintVisible: true,
  });
}

/**
 * Stop watchers and drop store rows that do not belong to the given session.
 * Call before hydrating a newly selected session to avoid leaking SSE/poll.
 * Pass an empty session id to tear down every tracked task (e.g. blank "new" chat).
 * Orphan rows with empty sessionId are always treated as stale on switch.
 */
export function stopBackgroundWatchersNotInSession(
  backendSessionId: string,
): void {
  const store = useBackgroundTasksStore.getState();
  const staleIds = !backendSessionId
    ? store.tasks.map((t) => t.toolCallId)
    : store.tasks
        .filter((t) => !t.sessionId || t.sessionId !== backendSessionId)
        .map((t) => t.toolCallId);
  for (const id of staleIds) {
    stopBackgroundTaskWatcher(id);
  }
  if (staleIds.length > 0) {
    store.removeTasks(staleIds);
  }
}

/**
 * Rehydrate the background task panel from the backend list of still-offloaded
 * tool calls. Idempotent with live registerBackgroundTask paths.
 */
export async function hydrateBackgroundTasksForSession(
  backendSessionId: string,
): Promise<void> {
  if (!backendSessionId) return;
  try {
    const { items } = await toolCallsApi.list(backendSessionId);
    for (const item of items) {
      if (item.status !== "offloaded") continue;
      const elapsedMs = Math.max(0, Math.round((item.elapsed || 0) * 1000));
      registerBackgroundTask({
        sessionId: item.session_id || backendSessionId,
        toolCallId: item.tool_call_id,
        toolName: item.tool_name || item.tool_call_id,
        startTime: Date.now() - elapsedMs,
      });
    }
  } catch (err) {
    console.error(
      "[hydrateBackgroundTasksForSession] list failed:",
      backendSessionId,
      err,
    );
  }
}
