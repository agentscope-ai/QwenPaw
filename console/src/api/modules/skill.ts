import { request } from "../request";
import { getApiUrl } from "../config";
import type { HubSkillSpec, SkillSpec } from "../types";

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

  installHubSkill: (payload: {
    bundle_url: string;
    version?: string;
    enable?: boolean;
    overwrite?: boolean;
  }) =>
    request<{
      installed: boolean;
      name: string;
      enabled: boolean;
      source_url: string;
    }>("/skills/hub/install", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

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

    const response = await fetch(url, {
      method: "POST",
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
