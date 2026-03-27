import { request } from "../request";
import { getApiUrl } from "../config";
import { buildAuthHeaders } from "../authHeaders";
import type {
  BuiltinImportSpec,
  HubInstallTaskResponse,
  HubSkillSpec,
  PoolSkillSpec,
  SkillSpec,
  WorkspaceSkillSummary,
} from "../types";

// Declare VITE_API_BASE_URL as global (injected by Vite)
declare const VITE_API_BASE_URL: string;

function getStreamApiUrl(): string {
  const base = typeof VITE_API_BASE_URL === "string" ? VITE_API_BASE_URL : "";
  return `${base}/api`;
}

async function _uploadZip(
  endpoint: string,
  file: File,
  options?: {
    enable?: boolean;
    overwrite?: boolean;
    target_name?: string;
    rename_map?: Record<string, string>;
  },
): Promise<Record<string, unknown>> {
  const formData = new FormData();
  formData.append("file", file);

  const params = new URLSearchParams();
  if (options?.enable !== undefined) {
    params.set("enable", String(options.enable));
  }
  if (options?.overwrite !== undefined) {
    params.set("overwrite", String(options.overwrite));
  }
  if (options?.target_name) {
    params.set("target_name", options.target_name);
  }
  if (options?.rename_map && Object.keys(options.rename_map).length) {
    params.set("rename_map", JSON.stringify(options.rename_map));
  }
  const qs = params.toString();
  const url = getApiUrl(`${endpoint}${qs ? `?${qs}` : ""}`);

  const headers = buildAuthHeaders();

  const response = await fetch(url, {
    method: "POST",
    headers,
    body: formData,
  });

  if (!response.ok) {
    throw new Error(await response.text());
  }

  return await response.json();
}

export const skillApi = {
  listSkills: (agentId?: string) => {
    const opts: RequestInit = {};
    if (agentId) opts.headers = new Headers({ "X-Agent-Id": agentId });
    return request<SkillSpec[]>("/skills", opts);
  },

  listSkillWorkspaces: () =>
    request<WorkspaceSkillSummary[]>("/skills/workspaces"),

  listSkillPoolSkills: () => request<PoolSkillSpec[]>("/skills/pool"),

  searchHubSkills: (q: string, limit: number = 20) =>
    request<HubSkillSpec[]>(
      `/skills/hub/search?q=${encodeURIComponent(q)}&limit=${limit}`,
    ),

  createSkill: (
    skillName: string,
    content: string,
    config?: Record<string, unknown>,
    enable?: boolean,
  ) =>
    request<{ created: boolean; name: string }>("/skills", {
      method: "POST",
      body: JSON.stringify({
        name: skillName,
        content,
        config,
        enable,
      }),
    }),

  saveSkill: (payload: {
    name: string;
    content: string;
    source_name?: string;
    config?: Record<string, unknown>;
  }) =>
    request<{
      success: boolean;
      mode: "edit" | "rename" | "noop";
      name: string;
    }>("/skills/save", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  createSkillPoolSkill: (payload: {
    name: string;
    content: string;
    config?: Record<string, unknown>;
  }) =>
    request<{ created: boolean; name: string }>("/skills/pool/create", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  saveSkillPoolSkill: (payload: {
    name: string;
    content: string;
    source_name?: string;
    config?: Record<string, unknown>;
  }) =>
    request<{
      success: boolean;
      mode: "edit" | "rename" | "noop";
      name: string;
    }>("/skills/pool/save", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  enableSkill: (skillName: string) =>
    request<void>(`/skills/${encodeURIComponent(skillName)}/enable`, {
      method: "POST",
    }),

  disableSkill: (skillName: string) =>
    request<void>(`/skills/${encodeURIComponent(skillName)}/disable`, {
      method: "POST",
    }),

  batchEnableSkills: (skillNames: string[]) =>
    request<void>("/skills/batch-enable", {
      method: "POST",
      body: JSON.stringify(skillNames),
    }),

  deleteSkill: (skillName: string) =>
    request<{ deleted: boolean }>(`/skills/${encodeURIComponent(skillName)}`, {
      method: "DELETE",
    }),

  startHubSkillInstall: (payload: {
    bundle_url: string;
    version?: string;
    enable?: boolean;
    overwrite?: boolean;
    target_name?: string;
  }) =>
    request<HubInstallTaskResponse>("/skills/hub/install/start", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  importPoolSkillFromHub: (payload: {
    bundle_url: string;
    version?: string;
    overwrite?: boolean;
    target_name?: string;
  }) =>
    request<{
      installed: boolean;
      name: string;
      enabled: boolean;
      source_url: string;
    }>("/skills/pool/import", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  getHubSkillInstallStatus: (taskId: string) =>
    request<HubInstallTaskResponse>(
      `/skills/hub/install/status/${encodeURIComponent(taskId)}`,
    ),

  cancelHubSkillInstall: (taskId: string) =>
    request<{ task_id: string; status: string }>(
      `/skills/hub/install/cancel/${encodeURIComponent(taskId)}`,
      {
        method: "POST",
      },
    ),

  listPoolBuiltinSources: () =>
    request<BuiltinImportSpec[]>("/skills/pool/builtin-sources"),

  importSelectedPoolBuiltins: (payload: {
    skill_names: string[];
    overwrite_conflicts?: boolean;
  }) =>
    request<{
      imported: string[];
      updated: string[];
      unchanged: string[];
      conflicts: Array<{
        skill_name: string;
        source_version_text?: string;
        current_version_text?: string;
        current_source?: string;
      }>;
    }>("/skills/pool/import-builtin", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  updatePoolBuiltin: (skillName: string) =>
    request<Record<string, unknown>>(
      `/skills/pool/${encodeURIComponent(skillName)}/update-builtin`,
      { method: "POST" },
    ),

  deleteSkillPoolSkill: (skillName: string) =>
    request<{ deleted: boolean }>(
      `/skills/pool/${encodeURIComponent(skillName)}`,
      {
        method: "DELETE",
      },
    ),

  uploadWorkspaceSkillToPool: (payload: {
    workspace_id: string;
    skill_name: string;
    new_name?: string;
    overwrite?: boolean;
  }) =>
    request<{ success: boolean; name: string }>("/skills/pool/upload", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  downloadSkillPoolSkill: (payload: {
    skill_name: string;
    targets: Array<{ workspace_id: string; target_name?: string }>;
    all_workspaces?: boolean;
    overwrite?: boolean;
  }) =>
    request<{
      downloaded: Array<{
        workspace_id: string;
        workspace_name?: string;
        name: string;
      }>;
      conflicts?: Array<{
        reason?: string;
        workspace_id?: string;
        workspace_name?: string;
        suggested_name?: string;
      }>;
    }>("/skills/pool/download", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  updateSkillChannels: (skillName: string, channels: string[]) =>
    request<{ updated: boolean; channels: string[] }>(
      `/skills/${encodeURIComponent(skillName)}/channels`,
      {
        method: "PUT",
        body: JSON.stringify(channels),
      },
    ),

  getSkillConfig: (skillName: string) =>
    request<{ config: Record<string, unknown> }>(
      `/skills/${encodeURIComponent(skillName)}/config`,
    ),

  updateSkillConfig: (skillName: string, config: Record<string, unknown>) =>
    request<{ updated: boolean }>(
      `/skills/${encodeURIComponent(skillName)}/config`,
      {
        method: "PUT",
        body: JSON.stringify({ config }),
      },
    ),

  deleteSkillConfig: (skillName: string) =>
    request<{ cleared: boolean }>(
      `/skills/${encodeURIComponent(skillName)}/config`,
      { method: "DELETE" },
    ),

  getPoolSkillConfig: (skillName: string) =>
    request<{ config: Record<string, unknown> }>(
      `/skills/pool/${encodeURIComponent(skillName)}/config`,
    ),

  updatePoolSkillConfig: (skillName: string, config: Record<string, unknown>) =>
    request<{ updated: boolean }>(
      `/skills/pool/${encodeURIComponent(skillName)}/config`,
      {
        method: "PUT",
        body: JSON.stringify({ config }),
      },
    ),

  deletePoolSkillConfig: (skillName: string) =>
    request<{ cleared: boolean }>(
      `/skills/pool/${encodeURIComponent(skillName)}/config`,
      { method: "DELETE" },
    ),

  streamOptimizeSkill: async function (
    content: string,
    onChunk: (text: string) => void,
    signal: AbortSignal,
    language: string = "en",
  ): Promise<void> {
    const apiUrl = getStreamApiUrl();

    const response = await fetch(`${apiUrl}/skills/ai/optimize/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ content, language }),
      signal,
    });

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error("No reader available");
    }

    const decoder = new TextDecoder();
    let buffer = "";

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");

        for (let i = 0; i < lines.length - 1; i++) {
          const line = lines[i].trim();
          if (line.startsWith("data: ")) {
            const data = line.slice(6);
            try {
              const parsed = JSON.parse(data);
              if (parsed.text) {
                onChunk(parsed.text);
              } else if (parsed.error) {
                throw new Error(parsed.error);
              } else if (parsed.done) {
                return;
              }
            } catch {
              // Ignore malformed chunks.
            }
          }
        }

        buffer = lines[lines.length - 1];
      }
    } finally {
      reader.releaseLock();
    }
  },

  uploadSkill: (
    file: File,
    options?: {
      enable?: boolean;
      overwrite?: boolean;
      target_name?: string;
      rename_map?: Record<string, string>;
    },
  ) =>
    _uploadZip("/skills/upload", file, options) as Promise<{
      imported: string[];
      count: number;
      enabled: boolean;
      conflicts?: Array<{
        reason: string;
        skill_name: string;
        suggested_name: string;
      }>;
    }>,

  uploadSkillPoolZip: (
    file: File,
    options?: {
      overwrite?: boolean;
      target_name?: string;
      rename_map?: Record<string, string>;
    },
  ) =>
    _uploadZip("/skills/pool/upload-zip", file, options) as Promise<{
      imported: string[];
      count: number;
      conflicts?: Array<{
        reason: string;
        skill_name: string;
        suggested_name: string;
      }>;
    }>,
};
