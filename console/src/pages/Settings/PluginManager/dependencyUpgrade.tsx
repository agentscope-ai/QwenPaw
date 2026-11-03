import { Modal } from "antd";
import type { TFunction } from "i18next";
import { buildAuthHeaders } from "@/api/authHeaders";
import { getApiUrl } from "@/api/config";
import {
  applyDependencyUpgrade,
  cancelDependencyUpgrade,
  fetchDependencyUpgrade,
  PluginApiError,
  type DependencyUpgradeOperation,
  type InstallPluginResult,
} from "@/api/modules/plugin";

const active = new Map<
  string,
  {
    promise: Promise<InstallPluginResult | null>;
    foreground: boolean;
  }
>();
const statuses = new Set([
  "needs_confirmation",
  "preparing",
  "applying",
  "waiting_restart",
  "succeeded",
  "failed",
  "cancelled",
]);

export function getPendingUpgradeStorageKey(): string {
  const url = new URL(getApiUrl("/plugins"), window.location.href);
  url.username = url.password = url.search = url.hash = "";
  return `qwenpaw.plugin-dependency-upgrades:${JSON.stringify([
    url.href,
    buildAuthHeaders()["X-Agent-Id"] || "default",
  ])}`;
}

function pendingIds(key: string): string[] {
  try {
    const ids: unknown = JSON.parse(localStorage.getItem(key) || "[]");
    return Array.isArray(ids)
      ? ids.filter((id): id is string => typeof id === "string" && Boolean(id))
      : [];
  } catch {
    return [];
  }
}

function remember(key: string, id: string, keep: boolean) {
  const ids = new Set(pendingIds(key));
  if (keep) ids.add(id);
  else ids.delete(id);
  try {
    if (ids.size) localStorage.setItem(key, JSON.stringify([...ids]));
    else localStorage.removeItem(key);
  } catch {
    // Installation remains available when browser storage is disabled.
  }
}

function impact(operation: DependencyUpgradeOperation, t: TFunction) {
  return (
    <div>
      <p>{t(`pluginManager.dependencyUpgrade.status.${operation.status}`)}</p>
      <p>{operation.message}</p>
      <strong>{t("pluginManager.dependencyUpgrade.changes")}</strong>
      <ul>
        {operation.changes.map((change) => (
          <li key={change.name}>
            {change.name}: {change.current_version || "—"} →{" "}
            {change.target_version}
          </li>
        ))}
      </ul>
      <strong>{t("pluginManager.dependencyUpgrade.affected")}</strong>
      {operation.affected_instances.length ? (
        <ul>
          {operation.affected_instances.map((instance) => (
            <li key={`${instance.plugin_id}:${instance.instance_id}`}>
              {instance.plugin_id}
              {instance.instance_id && ` / ${instance.instance_id}`}
            </li>
          ))}
        </ul>
      ) : (
        <p>{t("pluginManager.dependencyUpgrade.noInstances")}</p>
      )}
      {operation.requires_restart && (
        <p>{t("pluginManager.dependencyUpgrade.restart")}</p>
      )}
      {operation.instructions?.map((instruction) => (
        <p key={instruction}>{instruction}</p>
      ))}
    </div>
  );
}

function confirm(operation: DependencyUpgradeOperation, t: TFunction) {
  return new Promise<boolean>((resolve) => {
    Modal.confirm({
      title: t("pluginManager.dependencyUpgrade.title"),
      content: impact(operation, t),
      okText: t("pluginManager.dependencyUpgrade.confirm"),
      cancelText: t("common.cancel"),
      onOk: () => resolve(true),
      onCancel: () => resolve(false),
    });
  });
}

function transient(error: unknown): boolean {
  const status = (error as PluginApiError | null)?.status;
  return (
    error instanceof TypeError ||
    status === 408 ||
    status === 429 ||
    (status !== undefined && status >= 500)
  );
}

async function followUpgrade(
  id: string,
  operation: DependencyUpgradeOperation | undefined,
  key: string,
  t: TFunction,
): Promise<InstallPluginResult | null> {
  let pluginId = operation?.plugin_id;
  let submitted = false;
  let cancelling = false;
  let failures = 0;
  let progress: ReturnType<typeof Modal.info> | undefined;
  const deadline = Date.now() + 10 * 60_000;
  const pause = (ms: number) =>
    new Promise((resolve) => setTimeout(resolve, ms));
  try {
    while (Date.now() < deadline) {
      if (getPendingUpgradeStorageKey() !== key) {
        throw new Error(t("pluginManager.dependencyUpgrade.resume"));
      }
      if (!operation) {
        try {
          operation = await fetchDependencyUpgrade(id);
          failures = 0;
        } catch (error) {
          if (!transient(error)) {
            const status = (error as PluginApiError | null)?.status;
            if (status === 404 || status === 410) remember(key, id, false);
            throw error;
          }
          if (failures++ >= 5) {
            throw new Error(t("pluginManager.dependencyUpgrade.resume"));
          }
          await pause(Math.min(1000 * 2 ** (failures - 1), 8000));
          continue;
        }
      }
      if (getPendingUpgradeStorageKey() !== key) {
        throw new Error(t("pluginManager.dependencyUpgrade.resume"));
      }
      if (
        !operation ||
        operation.id !== id ||
        !operation.plugin_id ||
        (pluginId && operation.plugin_id !== pluginId) ||
        !statuses.has(operation.status) ||
        !Array.isArray(operation.changes) ||
        !Array.isArray(operation.affected_instances)
      ) {
        throw new Error(t("pluginManager.dependencyUpgrade.invalid"));
      }
      pluginId = operation.plugin_id;
      if (operation.status === "succeeded") {
        if (!operation.result || operation.result.id !== pluginId) {
          throw new Error(t("pluginManager.dependencyUpgrade.invalid"));
        }
        remember(key, id, false);
        return operation.result;
      }
      if (operation.status === "cancelled") {
        remember(key, id, false);
        return null;
      }
      if (operation.status === "failed") {
        remember(key, id, false);
        throw new PluginApiError(
          operation.error?.message ||
            operation.message ||
            t("pluginManager.dependencyUpgrade.failed"),
          409,
          { code: operation.error?.code, instructions: operation.instructions },
        );
      }
      if (operation.status === "needs_confirmation") {
        if (submitted)
          throw new Error(
            t(
              `pluginManager.dependencyUpgrade.${
                cancelling ? "cancelFailed" : "notStarted"
              }`,
            ),
          );
        if (!(await confirm(operation, t))) {
          if (getPendingUpgradeStorageKey() !== key) return null;
          remember(key, id, true);
          submitted = cancelling = true;
          try {
            operation = await cancelDependencyUpgrade(id);
          } catch {
            // A lost cancellation response cannot establish that no upgrade ran.
            operation = undefined;
          }
          if (operation?.status === "cancelled") {
            remember(key, id, false);
            return null;
          }
          continue;
        }
        if (getPendingUpgradeStorageKey() !== key) {
          throw new Error(t("pluginManager.dependencyUpgrade.resume"));
        }
        remember(key, id, true);
        submitted = true;
        try {
          operation = await applyDependencyUpgrade(id);
        } catch (error) {
          if (!transient(error)) {
            const status = (error as PluginApiError | null)?.status;
            if (status === 404 || status === 410) remember(key, id, false);
            throw error;
          }
          // The backend may have committed before disconnecting; query, never replay.
          operation = undefined;
        }
        continue;
      }
      if (!progress) {
        progress = Modal.info({
          title: t("pluginManager.dependencyUpgrade.progress"),
          content: impact(operation, t),
          okText: t("pluginManager.dependencyUpgrade.background"),
        });
      } else {
        progress.update({ content: impact(operation, t) });
      }
      operation = undefined;
      await pause(1500);
    }
    throw new Error(t("pluginManager.dependencyUpgrade.resume"));
  } finally {
    progress?.destroy();
  }
}

function trackUpgrade(
  id: string,
  operation: DependencyUpgradeOperation | undefined,
  key: string,
  t: TFunction,
  foreground = false,
) {
  const taskKey = `${key}:${id}`;
  const existing = active.get(taskKey);
  if (existing) {
    if (foreground) existing.foreground = true;
    return existing;
  }
  const tracking = followUpgrade(id, operation, key, t).finally(() =>
    active.delete(taskKey),
  );
  const task = { promise: tracking, foreground };
  active.set(taskKey, task);
  return task;
}

export async function runPluginInstall<T>(
  install: () => Promise<T>,
  t: TFunction,
): Promise<T | InstallPluginResult | null> {
  try {
    return await install();
  } catch (error) {
    const failure = error as PluginApiError | null;
    if (
      failure?.code !== "DEPENDENCY_UPGRADE_REQUIRED" ||
      !failure.operation?.id
    )
      throw error;
    const task = trackUpgrade(
      failure.operation.id,
      failure.operation,
      getPendingUpgradeStorageKey(),
      t,
      true,
    );
    return task.promise.then(
      (result) => (task.foreground ? result : null),
      (error: unknown) => {
        if (task.foreground) throw error;
        return null;
      },
    );
  }
}

export function resumePendingPluginInstalls(
  t: TFunction,
  onSuccess: (result: InstallPluginResult) => void | Promise<void>,
  onError: (error: Error) => void,
): () => void {
  const key = getPendingUpgradeStorageKey();
  const tracking = new Set<string>();
  let disposed = false;
  const resume = () => {
    if (disposed || getPendingUpgradeStorageKey() !== key) return;
    for (const id of pendingIds(key)) {
      if (tracking.has(id) || active.get(`${key}:${id}`)?.foreground) continue;
      tracking.add(id);
      void trackUpgrade(id, undefined, key, t)
        .promise.then((result) => {
          if (!disposed && result) return onSuccess(result);
        })
        .catch((error: unknown) => {
          if (!disposed)
            onError(error instanceof Error ? error : new Error(String(error)));
        })
        .finally(() => tracking.delete(id));
    }
  };
  resume();
  window.addEventListener("online", resume);
  window.addEventListener("focus", resume);
  return () => {
    disposed = true;
    for (const [taskKey, task] of active) {
      if (taskKey.startsWith(`${key}:`)) task.foreground = false;
    }
    window.removeEventListener("online", resume);
    window.removeEventListener("focus", resume);
  };
}
