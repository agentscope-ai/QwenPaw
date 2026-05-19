import { useCallback, useRef, useState } from "react";
import api from "../../../api";
import { invalidateSkillCache } from "../../../api/modules/skill";
import type { MarketResult } from "../../../api/modules/market";

export type InstallTarget = "pool" | "workspace";

export type InstallStatus =
  | "queued"
  | "installing"
  | "completed"
  | "failed"
  | "cancelled";

export interface InstallQueueItem {
  id: string;
  result: MarketResult;
  target: InstallTarget;
  status: InstallStatus;
  message: string;
  installedName?: string;
}

export interface UseMarketInstallOptions {
  selectedAgent: string;
  onConflict?: (
    item: InstallQueueItem,
    suggestedName: string,
  ) => Promise<string | null>;
  onSuccess?: (item: InstallQueueItem) => void;
  onError?: (item: InstallQueueItem, err: unknown) => void;
}

interface ConflictDetail {
  skill_name?: string;
  suggested_name?: string;
}

function parseConflict(error: unknown): ConflictDetail | null {
  if (!error || typeof error !== "object") return null;
  const detail = (error as { detail?: unknown }).detail;
  if (detail && typeof detail === "object") {
    const d = detail as ConflictDetail;
    if (d.suggested_name) return d;
  }
  return null;
}

const POLL_MS = 1000;
const TIMEOUT_MS = 90_000;

export function useMarketInstall(opts: UseMarketInstallOptions) {
  const [queue, setQueueState] = useState<InstallQueueItem[]>([]);
  const queueRef = useRef<InstallQueueItem[]>([]);
  const runningRef = useRef(false);
  const cancelledRef = useRef<Set<string>>(new Set());
  const currentTaskIdRef = useRef<string | null>(null);

  const setQueue = useCallback((next: InstallQueueItem[]) => {
    queueRef.current = next;
    setQueueState(next);
  }, []);

  const updateItem = useCallback(
    (id: string, patch: Partial<InstallQueueItem>) => {
      const next = queueRef.current.map((it) =>
        it.id === id ? { ...it, ...patch } : it,
      );
      setQueue(next);
    },
    [setQueue],
  );

  const enqueue = useCallback(
    (results: MarketResult[], target: InstallTarget) => {
      const items: InstallQueueItem[] = results.map((r) => ({
        id: `${r.source}:${r.slug}:${Date.now()}:${Math.random()
          .toString(36)
          .slice(2, 7)}`,
        result: r,
        target,
        status: "queued",
        message: "",
      }));
      setQueue([...queueRef.current, ...items]);
      void runQueue();
      return items;
    },
    [setQueue],
  );

  const runQueue = useCallback(async () => {
    if (runningRef.current) return;
    runningRef.current = true;
    try {
      while (true) {
        const next = queueRef.current.find((it) => it.status === "queued");
        if (!next) break;
        if (cancelledRef.current.has(next.id)) {
          // Status tag already says "cancelled"; no extra English label.
          updateItem(next.id, { status: "cancelled", message: "" });
          continue;
        }
        await installOne(next, undefined);
      }
    } finally {
      runningRef.current = false;
    }
  }, [updateItem]);

  const installOne = useCallback(
    async (item: InstallQueueItem, overrideName: string | undefined) => {
      updateItem(item.id, { status: "installing", message: "" });
      try {
        if (item.target === "pool") {
          const result = await api.importPoolSkillFromHub({
            bundle_url: item.result.source_url,
            target_name: overrideName,
          });
          invalidateSkillCache({ pool: true });
          updateItem(item.id, {
            status: "completed",
            installedName: result.name,
            message: result.name,
          });
          opts.onSuccess?.({ ...item, status: "completed" });
        } else {
          await installWorkspace(item, overrideName);
        }
      } catch (err) {
        const conflict = parseConflict(err);
        if (conflict?.suggested_name && opts.onConflict) {
          const newName = await opts.onConflict(item, conflict.suggested_name);
          if (newName) {
            await installOne(item, newName);
            return;
          }
          updateItem(item.id, { status: "cancelled", message: "" });
          return;
        }
        // Real server-side error: keep the upstream text — it's
        // diagnostic, not a state label. Prefix it on render so the
        // user sees "Failed: <message>" / "失败：<message>".
        const msg = err instanceof Error ? err.message : String(err);
        updateItem(item.id, { status: "failed", message: msg });
        opts.onError?.({ ...item, status: "failed" }, err);
      }
    },
    [opts, updateItem],
  );

  const installWorkspace = useCallback(
    async (item: InstallQueueItem, overrideName: string | undefined) => {
      const agentId = opts.selectedAgent;
      const task = await api.startHubSkillInstall(
        {
          bundle_url: item.result.source_url,
          enable: true,
          target_name: overrideName,
        },
        agentId,
      );
      currentTaskIdRef.current = task.task_id;
      const startedAt = Date.now();
      try {
        while (currentTaskIdRef.current === task.task_id) {
          if (cancelledRef.current.has(item.id)) {
            await api.cancelHubSkillInstall(task.task_id, agentId);
            updateItem(item.id, { status: "cancelled", message: "" });
            return;
          }
          const status = await api.getHubSkillInstallStatus(
            task.task_id,
            agentId,
          );
          if (status.status === "completed" && status.result?.installed) {
            const installedName = String(status.result.name || "");
            invalidateSkillCache({ agentId });
            updateItem(item.id, {
              status: "completed",
              installedName,
              message: installedName,
            });
            opts.onSuccess?.({ ...item, status: "completed" });
            return;
          }
          if (status.status === "failed") {
            // Throw with the server's message (already localized
            // upstream when possible). Empty string means installer
            // gave no detail — let the status tag stand alone.
            throw new Error(status.error || "");
          }
          if (status.status === "cancelled") {
            updateItem(item.id, { status: "cancelled", message: "" });
            return;
          }
          if (Date.now() - startedAt > TIMEOUT_MS) {
            await api.cancelHubSkillInstall(task.task_id, agentId);
            updateItem(item.id, {
              status: "failed",
              message: "__TIMED_OUT__",
            });
            return;
          }
          await new Promise((res) => window.setTimeout(res, POLL_MS));
        }
      } finally {
        if (currentTaskIdRef.current === task.task_id) {
          currentTaskIdRef.current = null;
        }
      }
    },
    [opts, updateItem],
  );

  const cancel = useCallback(
    (id: string) => {
      cancelledRef.current.add(id);
      const taskId = currentTaskIdRef.current;
      if (taskId) {
        void api.cancelHubSkillInstall(taskId, opts.selectedAgent);
      }
    },
    [opts.selectedAgent],
  );

  const retry = useCallback(
    (id: string) => {
      if (!queueRef.current.some((it) => it.id === id)) return;
      cancelledRef.current.delete(id);
      updateItem(id, { status: "queued", message: "" });
      void runQueue();
    },
    [runQueue, updateItem],
  );

  const clearCompleted = useCallback(() => {
    setQueue(
      queueRef.current.filter(
        (it) => it.status === "queued" || it.status === "installing",
      ),
    );
  }, [setQueue]);

  return { queue, enqueue, cancel, retry, clearCompleted };
}
