import { request } from "../request";
import type { HubSkillSpec, SkillSpec } from "../types";

// Declare BASE_URL as global (injected by Vite)
declare const BASE_URL: string;

// Get the API base URL for streaming requests
function getStreamApiUrl(): string {
  const base = (typeof BASE_URL !== "undefined" ? BASE_URL : "") || "";
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

  // Stream optimize skill with SSE (returns controller for abort)
  streamOptimizeSkill: function (
    content: string,
    onChunk: (text: string) => void,
    signal: AbortSignal,
  ): Promise<void> {
    return new Promise(async (resolve, reject) => {
      const apiUrl = getStreamApiUrl();
      
      try {
        const response = await fetch(`${apiUrl}/skills/ai/optimize/stream`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ content }),
          signal,
        });

        if (!response.ok) {
          reject(new Error(`HTTP error! status: ${response.status}`));
          return;
        }

        const reader = response.body?.getReader();
        if (!reader) {
          reject(new Error("No reader available"));
          return;
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
                    reject(new Error(parsed.error));
                    return;
                  } else if (parsed.done) {
                    resolve();
                    return;
                  }
                } catch {
                  // Skip invalid JSON
                }
              }
            }

            buffer = lines[lines.length - 1];
          }
          resolve();
        } finally {
          reader.releaseLock();
        }
      } catch (err: any) {
        if (err.name === "AbortError") {
          resolve(); // Normal abort, not an error
        } else {
          reject(err);
        }
      }
    });
  },
};
