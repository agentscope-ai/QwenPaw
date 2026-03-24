import { request } from "../request";
import { getApiUrl } from "../config";
import { buildAuthHeaders } from "../authHeaders";
import type { HubSkillSpec, SkillSpec } from "../types";

// Declare BASE_URL as global (injected by Vite)
declare const BASE_URL: string;

// Get the API base URL for streaming requests
function getStreamApiUrl(): string {
  const base = typeof BASE_URL === "string" ? BASE_URL : "";
  return `${base}/api`;
}

export const skillApi = {
  listSkills: () => request<SkillSpec[]>("/skills"),

  createSkill: (skillName: string, content: string) =>
    request<Record<string, unknown>>("/skills", {
      method: "POST",
      body: JSON.stringify({
        name: skillName,
        content: content,
      }),
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

  searchHubSkills: (query: string, limit = 20) =>
    request<HubSkillSpec[]>(
      `/skills/hub/search?q=${encodeURIComponent(query)}&limit=${limit}`,
    ),

  installHubSkill: (
    payload: {
      bundle_url: string;
      version?: string;
      enable?: boolean;
      overwrite?: boolean;
    },
    options?: { signal?: AbortSignal },
  ) =>
    request<{
      installed: boolean;
      name: string;
      enabled: boolean;
      source_url: string;
    }>("/skills/hub/install", {
      method: "POST",
      body: JSON.stringify(payload),
      signal: options?.signal,
    }),

  startHubSkillInstall: (payload: {
    bundle_url: string;
    version?: string;
    enable?: boolean;
    overwrite?: boolean;
  }) =>
    request<{
      task_id: string;
      bundle_url: string;
      version: string;
      enable: boolean;
      overwrite: boolean;
      status: "pending" | "importing" | "completed" | "failed" | "cancelled";
      error: string | null;
      result: {
        installed: boolean;
        name: string;
        enabled: boolean;
        source_url: string;
      } | null;
      created_at: number;
      updated_at: number;
    }>("/skills/hub/install/start", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  getHubSkillInstallStatus: (taskId: string) =>
    request<{
      task_id: string;
      bundle_url: string;
      version: string;
      enable: boolean;
      overwrite: boolean;
      status: "pending" | "importing" | "completed" | "failed" | "cancelled";
      error: string | null;
      result: {
        installed: boolean;
        name: string;
        enabled: boolean;
        source_url: string;
      } | null;
      created_at: number;
      updated_at: number;
    }>(`/skills/hub/install/status/${encodeURIComponent(taskId)}`),

  cancelHubSkillInstall: (taskId: string) =>
    request<{ task_id: string; status: string }>(
      `/skills/hub/install/cancel/${encodeURIComponent(taskId)}`,
      {
        method: "POST",
      },
    ),

  // Stream optimize skill with SSE (supports abort via signal)
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
              // Skip invalid JSON
            }
          }
        }

        buffer = lines[lines.length - 1];
      }
    } finally {
      reader.releaseLock();
    }
  },

  uploadSkill: async (
    file: File,
    options?: { enable?: boolean; overwrite?: boolean },
  ): Promise<{ imported: string[]; count: number; enabled: boolean }> => {
    const formData = new FormData();
    formData.append("file", file);

    const params = new URLSearchParams();
    if (options?.enable !== undefined) {
      params.set("enable", String(options.enable));
    }
    if (options?.overwrite !== undefined) {
      params.set("overwrite", String(options.overwrite));
    }
    const qs = params.toString();
    const url = getApiUrl(`/skills/upload${qs ? `?${qs}` : ""}`);

    const headers = buildAuthHeaders();

    const response = await fetch(url, {
      method: "POST",
      headers,
      body: formData,
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(
        `Upload failed: ${response.status} ${response.statusText} - ${errorText}`,
      );
    }

    return await response.json();
  },
};
