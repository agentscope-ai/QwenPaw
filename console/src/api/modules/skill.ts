import { request } from "../request";
import type {
  HubSkillSpec,
  SkillConfigUpdatePayload,
  SkillConfigView,
  SkillSpec,
} from "../types";

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

  getSkillConfig: (skillName: string) =>
    request<SkillConfigView>(`/skills/${encodeURIComponent(skillName)}/config`),

  updateSkillConfig: (skillName: string, payload: SkillConfigUpdatePayload) =>
    request<SkillConfigView>(
      `/skills/${encodeURIComponent(skillName)}/config`,
      {
        method: "PUT",
        body: JSON.stringify(payload),
      },
    ),

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
};
