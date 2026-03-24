import { request } from "../request";
import { getApiUrl } from "../config";
import { buildAuthHeaders } from "../authHeaders";
import type { HubSkillSpec, SkillSpec } from "../types";

export const defaultSkillApi = {
  listDefaultSkills: () => request<SkillSpec[]>("/default-skills"),

  createDefaultSkill: (skill: SkillSpec) =>
    request<Record<string, unknown>>("/default-skills", {
      method: "POST",
      body: JSON.stringify({
        name: skill.name,
        content: skill.content,
        description: skill.description,
        source: skill.source,
        path: skill.path,
      }),
    }),

  enableSkillInAgent: (skillName: string) =>
    request<void>(`/default-skills/${encodeURIComponent(skillName)}/enable`, {
      method: "POST",
    }),

  disableSkillInAgent: (skillName: string) =>
    request<void>(`/default-skills/${encodeURIComponent(skillName)}/disable`, {
      method: "POST",
    }),

  moveToInactive: (skillName: string) =>
    request<void>(`/default-skills/${encodeURIComponent(skillName)}/move-to-inactive`, {
      method: "POST",
    }),

  moveToBuiltin: (skillName: string) =>
    request<void>(`/default-skills/${encodeURIComponent(skillName)}/move-to-builtin`, {
      method: "POST",
    }),

  deleteInactiveSkill: (skillName: string) =>
    request<{ deleted: boolean }>(`/default-skills/${encodeURIComponent(skillName)}`, {
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
      overwrite?: boolean;
    },
    options?: { signal?: AbortSignal },
  ) =>
    request<{
      installed: boolean;
      name: string;
      enabled: boolean;
      source_url: string;
    }>("/default-skills/hub/install", {
      method: "POST",
      body: JSON.stringify(payload),
      signal: options?.signal,
    }),

  startHubSkillInstall: (payload: {
    bundle_url: string;
    version?: string;
    overwrite?: boolean;
  }) =>
    request<{
      task_id: string;
      bundle_url: string;
      version: string;
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
    }>("/default-skills/hub/install/start", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  getHubSkillInstallStatus: (taskId: string) =>
    request<{
      task_id: string;
      bundle_url: string;
      version: string;
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
    }>(`/default-skills/hub/install/${encodeURIComponent(taskId)}`),

  cancelHubSkillInstall: (taskId: string) =>
    request<{ cancelled: boolean }>(
      `/default-skills/hub/install/${encodeURIComponent(taskId)}/cancel`,
      {
        method: "POST",
      },
    ),

  uploadDefaultSkill: async (
    file: File,
    options?: { overwrite?: boolean },
  ): Promise<{ imported: string[]; count: number }> => {
    const formData = new FormData();
    formData.append("file", file);

    const params = new URLSearchParams();
    if (options?.overwrite !== undefined) {
      params.set("overwrite", String(options.overwrite));
    }
    const qs = params.toString();
    const url = getApiUrl(`/default-skills/upload${qs ? `?${qs}` : ""}`);

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
