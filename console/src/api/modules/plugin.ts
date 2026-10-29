import { notifyPluginChange } from "../../utils/pluginChangeEvents";
import { getApiUrl } from "../config";
import { buildAuthHeaders } from "../authHeaders";
import { formatApiError, responseErrorMessage } from "../error";
import { requestWithPluginBusyConfirmation } from "../pluginBusy";

/** Matches the backend ``PluginType`` enum values. */
export type PluginType =
  | "tool"
  | "provider"
  | "hook"
  | "command"
  | "frontend"
  | "channel"
  | "memory"
  | "hub"
  | "app"
  | "general";

/**
 * A single plugin record returned by `GET /api/plugins`.
 */
export interface PluginInfo {
  id: string;
  name: string;
  version: string;
  description: string;
  author?: string;
  enabled: boolean;
  /** Whether the plugin is currently loaded in memory. */
  loaded: boolean;
  status?: string;
  /** Primary capability type declared in plugin.json. */
  plugin_type: PluginType;
  /** Frontend JS entry-point path (if any). */
  frontend_entry?: string;
}

export interface InstallPluginResult {
  id: string;
  name: string;
  version: string;
  description: string;
  author?: string;
  loaded: boolean;
  message: string;
}

export interface RepairPluginDependenciesResult {
  id: string;
  status: string;
  enabled: boolean;
  diagnostics: string[];
  message: string;
}

export interface DependencyUpgradeOperation {
  id: string;
  plugin_id: string;
  status:
    | "needs_confirmation"
    | "preparing"
    | "applying"
    | "waiting_restart"
    | "succeeded"
    | "failed"
    | "cancelled";
  changes: {
    name: string;
    current_version: string | null;
    target_version: string;
  }[];
  affected_instances: {
    plugin_id: string;
    instance_id: string | null;
    generation: number | null;
    origin: string;
    active: boolean;
  }[];
  requires_restart: boolean;
  message: string;
  result?: InstallPluginResult;
  error?: { code: string; message: string } | null;
  retryable?: boolean;
  instructions?: string[];
}

interface PluginErrorDetail {
  code?: string;
  operation?: DependencyUpgradeOperation;
  instructions?: string[];
}

export class PluginApiError extends Error {
  readonly status: number;
  readonly code?: string;
  readonly operation?: DependencyUpgradeOperation;
  readonly instructions: string[];

  constructor(message: string, status: number, detail: PluginErrorDetail = {}) {
    const instructions = Array.isArray(detail.instructions)
      ? detail.instructions.filter(
          (item): item is string => typeof item === "string" && Boolean(item),
        )
      : [];
    super(
      [message, ...instructions.filter((item) => !message.includes(item))].join(
        "\n",
      ),
    );
    this.name = "PluginApiError";
    this.status = status;
    this.code = detail.code;
    this.operation = detail.operation;
    this.instructions = instructions;
  }
}

async function pluginResponseError(response: Response, fallback: string) {
  const payload: unknown = await response.json().catch(() => null);
  const detail =
    payload && typeof payload === "object" && "detail" in payload
      ? payload.detail
      : null;
  return new PluginApiError(
    formatApiError(payload, fallback),
    response.status,
    detail && typeof detail === "object" ? detail : {},
  );
}

async function requestDependencyUpgrade(
  id: string,
  method: "GET" | "POST" | "DELETE",
): Promise<DependencyUpgradeOperation> {
  const path = `/plugins/dependency-upgrades/${encodeURIComponent(id)}${
    method === "POST" ? "/apply" : ""
  }`;
  const response = await fetch(getApiUrl(path), {
    method,
    headers: buildAuthHeaders(),
  });
  if (!response.ok) {
    throw await pluginResponseError(
      response,
      `Dependency upgrade failed (${response.status})`,
    );
  }
  return response.json();
}

export const fetchDependencyUpgrade = (id: string) =>
  requestDependencyUpgrade(id, "GET");

export const applyDependencyUpgrade = (id: string) =>
  requestDependencyUpgrade(id, "POST");

export const cancelDependencyUpgrade = (id: string) =>
  requestDependencyUpgrade(id, "DELETE");

export interface PluginStatus {
  id: string;
  loaded: boolean;
  status?: string;
  enabled: boolean;
  version?: string;
}

/** Entry from ``GET /api/plugins/catalog`` (official CDN manifest). */
export interface OfficialPluginCatalogEntry {
  id: string;
  plugin_id: string;
  name: string;
  description: string;
  /** Locale-keyed descriptions, e.g. { "zh-CN": "...", "en-US": "..." } */
  description_i18n?: Record<string, string>;
  version: string;
  author: string;
  kind: string;
  size: string;
  sha256: string;
  install_url: string;
  installed: boolean;
  installed_version?: string;
  upgrade_available: boolean;
}

export interface PluginUpdateInfo {
  version: string;
  source: string;
  name: string;
}

export interface OfficialPluginCatalog {
  updated_at: string | null;
  plugins: OfficialPluginCatalogEntry[];
  error?: string | null;
}

/**
 * Fetch the list of loaded plugins from the backend.
 */
export async function fetchPlugins(): Promise<PluginInfo[]> {
  const response = await fetch(getApiUrl("/plugins"), {
    headers: buildAuthHeaders(),
  });

  if (!response.ok) {
    console.warn("[plugin] Failed to fetch plugin list:", response.status);
    return [];
  }

  return response.json();
}

/**
 * Install a plugin from a local path or HTTP(S) URL via hot-reload.
 */
export async function fetchPluginCatalog(): Promise<OfficialPluginCatalog> {
  const response = await fetch(getApiUrl("/plugins/catalog"), {
    headers: buildAuthHeaders(),
  });

  if (!response.ok) {
    throw new Error(
      await responseErrorMessage(
        response,
        `Failed to load plugin catalog (${response.status})`,
      ),
    );
  }

  return response.json();
}

export async function installPlugin(
  source: string,
  options?: { force?: boolean },
): Promise<InstallPluginResult> {
  const response = await requestWithPluginBusyConfirmation(
    (interruptTasks) =>
      fetch(getApiUrl("/plugins/install"), {
        method: "POST",
        headers: {
          ...buildAuthHeaders(),
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          source,
          force: options?.force ?? false,
          ...(interruptTasks ? { interrupt_tasks: true } : {}),
        }),
      }),
    "update",
  );

  if (!response.ok) {
    throw await pluginResponseError(
      response,
      `Install failed (${response.status})`,
    );
  }

  const result = await response.json();
  notifyPluginChange();
  return result;
}

/**
 * Install a plugin from a local ZIP file via hot-reload.
 */
export async function uploadPlugin(file: File): Promise<InstallPluginResult> {
  const form = new FormData();
  form.append("file", file);

  const response = await requestWithPluginBusyConfirmation(
    (interruptTasks) =>
      fetch(
        getApiUrl(
          `/plugins/upload${interruptTasks ? "?interrupt_tasks=true" : ""}`,
        ),
        {
          method: "POST",
          headers: buildAuthHeaders(),
          body: form,
        },
      ),
    "update",
  );

  if (!response.ok) {
    throw await pluginResponseError(
      response,
      `Upload failed (${response.status})`,
    );
  }

  const result = await response.json();
  notifyPluginChange();
  return result;
}

export async function repairPluginDependencies(
  pluginId: string,
): Promise<RepairPluginDependenciesResult> {
  const response = await fetch(
    getApiUrl(`/plugins/${encodeURIComponent(pluginId)}/repair-dependencies`),
    { method: "POST", headers: buildAuthHeaders() },
  );
  if (!response.ok) {
    throw await pluginResponseError(
      response,
      `Dependency repair failed (${response.status})`,
    );
  }
  return response.json();
}

/**
 * Uninstall (hot-unload + delete) a plugin by ID.
 */
export async function uninstallPlugin(pluginId: string): Promise<void> {
  const response = await requestWithPluginBusyConfirmation(
    (interruptTasks) =>
      fetch(
        getApiUrl(
          `/plugins/${pluginId}${
            interruptTasks ? "?interrupt_tasks=true" : ""
          }`,
        ),
        { method: "DELETE", headers: buildAuthHeaders() },
      ),
    "uninstall",
  );

  if (!response.ok) {
    throw new Error(
      await responseErrorMessage(
        response,
        `Uninstall failed (${response.status})`,
      ),
    );
  }
  notifyPluginChange();
}

/**
 * Fetch the runtime status of a single plugin.
 */
export async function fetchPluginStatus(
  pluginId: string,
): Promise<PluginStatus> {
  const response = await fetch(getApiUrl(`/plugins/${pluginId}/status`), {
    headers: buildAuthHeaders(),
  });

  if (!response.ok) {
    throw new Error(
      await responseErrorMessage(
        response,
        `Status fetch failed (${response.status})`,
      ),
    );
  }

  return response.json();
}
