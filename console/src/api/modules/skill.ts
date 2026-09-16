import type { SkillTargetResult } from "../types/skillGovernance";
import type { RequestOptions } from "../request";
import {
  captureSkillScope,
  scopedSkillRequest,
  skillRequestOptions,
  type SkillScope,
} from "../skillScope";
import { getApiUrl } from "../config";
import { buildAuthHeaders } from "../authHeaders";
import type {
  BuiltinImportSpec,
  BuiltinUpdateNotice,
  HubInstallTaskResponse,
  HubSkillSpec,
  PoolSkillSpec,
  PoolSkillDetail,
  SkillDetail,
  SkillSpec,
  WorkspaceSkillSummary,
} from "../types";

// Declare VITE_API_BASE_URL as global (injected by Vite)
declare const VITE_API_BASE_URL: string;

// Simple in-memory cache with TTL
const CACHE_TTL_MS = 30000; // 30 seconds
const apiCache = new Map<string, { data: unknown; timestamp: number }>();

function readCache<T>(key: string): T | null {
  const cached = apiCache.get(key);
  if (!cached) return null;
  if (Date.now() - cached.timestamp > CACHE_TTL_MS) {
    apiCache.delete(key);
    return null;
  }
  return cached.data as T;
}

function writeCache<T>(key: string, data: T): void {
  apiCache.set(key, { data, timestamp: Date.now() });
}

export function invalidateSkillCache(options?: {
  agentId?: string;
  workspaces?: boolean;
  pool?: boolean;
}): void {
  // Clear all skill-related cache entries
  for (const key of Array.from(apiCache.keys())) {
    const path = key.slice(key.indexOf("|") + 1);
    if (!path.startsWith("/skills")) continue;

    // If no specific options provided, clear all
    if (!options) {
      apiCache.delete(key);
      continue;
    }

    // Targeted invalidation based on options
    if (options.pool && path.startsWith("/skills/pool")) {
      apiCache.delete(key);
    } else if (options.workspaces && path === "/skills/workspaces") {
      apiCache.delete(key);
    } else if (options.agentId && path === `/skills?agent=${options.agentId}`) {
      apiCache.delete(key);
    } else if (options.agentId && path === "/skills") {
      // Also clear generic /skills cache when specific agent cache is invalidated
      apiCache.delete(key);
    }
  }
}

function getStreamApiUrl(): string {
  const base = typeof VITE_API_BASE_URL === "string" ? VITE_API_BASE_URL : "";
  return `${base}/api`;
}

export function createSkillApi(scope: SkillScope) {
  const request = <T>(path: string, options?: RequestOptions) =>
    scopedSkillRequest<T>(scope, path, options);
  const getCached = <T>(key: string) => {
    scope.assert();
    return readCache<T>(scope.key + "|" + key);
  };
  const setCache = <T>(key: string, data: T) => {
    scope.assert();
    writeCache(scope.key + "|" + key, data);
  };

  async function _uploadZip(
    endpoint: string,
    file: File,
    options?: {
      enable?: boolean;
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
    if (options?.target_name) {
      params.set("target_name", options.target_name);
    }
    if (options?.rename_map && Object.keys(options.rename_map).length) {
      params.set("rename_map", JSON.stringify(options.rename_map));
    }
    const qs = params.toString();
    const url = getApiUrl(`${endpoint}${qs ? `?${qs}` : ""}`);

    scope.assert();
    const headers = { ...buildAuthHeaders(), "X-Agent-Id": scope.agentId };

    const response = await fetch(url, {
      method: "POST",
      headers,
      body: formData,
      signal: scope.signal,
    });
    scope.assert();

    if (!response.ok) {
      const text = await response.text();
      const contentType = response.headers.get("content-type") || "";
      if (contentType.includes("application/json")) {
        // Format like request.ts so parseErrorDetail() can extract structured fields
        throw new Error(`${response.status} ${response.statusText} - ${text}`);
      }
      throw new Error(text || `Request failed: ${response.status}`);
    }

    const data = await response.json();
    scope.assert();
    return data;
  }

  return {
    listSkills: async (agentId?: string) => {
      const cacheKey = `/skills${agentId ? `?agent=${agentId}` : ""}`;
      const cached = getCached<SkillSpec[]>(cacheKey);
      if (cached) return cached;

      const opts: RequestInit = {};
      if (agentId) opts.headers = new Headers({ "X-Agent-Id": agentId });
      const data = await request<SkillSpec[]>("/skills", opts);
      setCache(cacheKey, data);
      return data;
    },

    listSkillWorkspaces: async () => {
      const cacheKey = "/skills/workspaces";
      const cached = getCached<WorkspaceSkillSummary[]>(cacheKey);
      if (cached) return cached;

      const data = await request<WorkspaceSkillSummary[]>("/skills/workspaces");
      setCache(cacheKey, data);
      return data;
    },

    listSkillPoolSkills: async () => {
      const cacheKey = "/skills/pool";
      const cached = getCached<PoolSkillSpec[]>(cacheKey);
      if (cached) return cached;

      const data = await request<PoolSkillSpec[]>("/skills/pool");
      // Ensure data is an array
      if (!Array.isArray(data)) {
        throw new Error(
          `Expected array from /skills/pool but got ${typeof data}`,
        );
      }
      setCache(cacheKey, data);
      return data;
    },

    getSkill: (skillName: string, agentId?: string) => {
      const opts: RequestInit = {};
      if (agentId) opts.headers = new Headers({ "X-Agent-Id": agentId });
      return request<SkillDetail>(
        `/skills/${encodeURIComponent(skillName)}`,
        opts,
      );
    },

    getPoolSkill: (skillName: string) =>
      request<PoolSkillDetail>(`/skills/pool/${encodeURIComponent(skillName)}`),

    refreshSkills: async (agentId?: string) => {
      const opts: RequestInit = { method: "POST" };
      if (agentId) opts.headers = new Headers({ "X-Agent-Id": agentId });
      const data = await request<SkillSpec[]>("/skills/refresh", opts);
      const cacheKey = `/skills${agentId ? `?agent=${agentId}` : ""}`;
      setCache(cacheKey, data);
      return data;
    },

    refreshSkillPool: async () => {
      const data = await request<PoolSkillSpec[]>("/skills/pool/refresh", {
        method: "POST",
      });
      // Ensure data is an array
      if (!Array.isArray(data)) {
        throw new Error(
          `Expected array from /skills/pool/refresh but got ${typeof data}`,
        );
      }
      setCache("/skills/pool", data);
      return data;
    },

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
      overwrite?: boolean;
      expected_content_hash?: string;
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
      overwrite?: boolean;
    }) =>
      request<{
        success: boolean;
        mode: "edit" | "rename" | "noop";
        name: string;
        results?: SkillTargetResult[];
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
      request<{
        results: Record<
          string,
          {
            success?: boolean;
            reason?: string;
            detail?: unknown;
          }
        >;
      }>("/skills/batch-enable", {
        method: "POST",
        body: JSON.stringify(skillNames),
      }),

    batchDisableSkills: (skillNames: string[]) =>
      request<{
        results: Record<string, { success: boolean; reason?: string }>;
      }>("/skills/batch-disable", {
        method: "POST",
        body: JSON.stringify(skillNames),
      }),

    batchDeleteSkills: (skillNames: string[]) =>
      request<{
        results: Record<string, { success: boolean; reason?: string }>;
      }>("/skills/batch-delete", {
        method: "POST",
        body: JSON.stringify(skillNames),
      }),

    batchDeletePoolSkills: (skillNames: string[]) =>
      request<{
        results: Record<string, { success: boolean; reason?: string }>;
      }>("/skills/pool/batch-delete", {
        method: "POST",
        body: JSON.stringify(skillNames),
      }),

    deleteSkill: (skillName: string) =>
      request<{ deleted: boolean }>(
        `/skills/${encodeURIComponent(skillName)}`,
        {
          method: "DELETE",
        },
      ),

    startHubSkillInstall: (
      payload: {
        bundle_url: string;
        version?: string;
        enable?: boolean;
        target_name?: string;
      },
      agentId?: string,
    ) => {
      const headers = agentId
        ? new Headers({ "X-Agent-Id": agentId })
        : undefined;
      return request<HubInstallTaskResponse>("/skills/hub/install/start", {
        method: "POST",
        headers,
        body: JSON.stringify(payload),
      });
    },

    importPoolSkillFromHub: (payload: {
      bundle_url: string;
      version?: string;
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

    getHubSkillInstallStatus: (taskId: string, agentId?: string) => {
      const headers = agentId
        ? new Headers({ "X-Agent-Id": agentId })
        : undefined;
      return request<HubInstallTaskResponse>(
        `/skills/hub/install/status/${encodeURIComponent(taskId)}`,
        { headers },
      );
    },

    cancelHubSkillInstall: (taskId: string, agentId?: string) => {
      const headers = agentId
        ? new Headers({ "X-Agent-Id": agentId })
        : undefined;
      return request<{ task_id: string; status: string }>(
        `/skills/hub/install/cancel/${encodeURIComponent(taskId)}`,
        { method: "POST", headers },
      );
    },

    listPoolBuiltinSources: () =>
      request<BuiltinImportSpec[]>("/skills/pool/builtin-sources"),

    getPoolBuiltinNotice: async () => {
      const cacheKey = "/skills/pool/builtin-notice";
      const cached = getCached<BuiltinUpdateNotice>(cacheKey);
      if (cached) return cached;

      const data = await request<BuiltinUpdateNotice>(
        "/skills/pool/builtin-notice",
      );
      setCache(cacheKey, data);
      return data;
    },

    importSelectedPoolBuiltins: (payload: {
      imports: Array<{ skill_name: string; language: string }>;
      overwrite_conflicts?: boolean;
    }) =>
      request<{
        imported: string[];
        updated: string[];
        unchanged: string[];
        conflicts: Array<{
          skill_name: string;
          language?: string;
          status?: string;
          source_name?: string;
          source_version_text?: string;
          current_version_text?: string;
          current_source?: string;
          current_language?: string;
        }>;
      }>("/skills/pool/import-builtin", {
        method: "POST",
        body: JSON.stringify(payload),
      }),

    updatePoolBuiltin: (skillName: string, language: string) =>
      request<Record<string, unknown>>(
        `/skills/pool/${encodeURIComponent(skillName)}/update-builtin`,
        {
          method: "POST",
          body: JSON.stringify({ language }),
        },
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
      overwrite?: boolean;
      preview_only?: boolean;
    }) =>
      request<{ success: boolean; name: string }>("/skills/pool/upload", {
        method: "POST",
        body: JSON.stringify(payload),
      }),

    downloadSkillPoolSkill: (payload: {
      skill_name: string;
      targets: Array<{ workspace_id: string }>;
      all_workspaces?: boolean;
      overwrite?: boolean;
      preview_only?: boolean;
    }) =>
      request<{
        downloaded: Array<{
          workspace_id: string;
          workspace_name?: string;
          name: string;
        }>;
        conflicts?: Array<{
          reason?: string;
          skill_name?: string;
          workspace_id?: string;
          workspace_name?: string;
          suggested_name?: string;
          current_version_text?: string;
          source_version_text?: string;
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

    updateSkillTags: (skillName: string, tags: string[]) =>
      request<{ updated: boolean; tags: string[] }>(
        `/skills/${encodeURIComponent(skillName)}/tags`,
        {
          method: "PUT",
          body: JSON.stringify(tags),
        },
      ),

    updatePoolSkillTags: (skillName: string, tags: string[]) =>
      request<{ updated: boolean; tags: string[] }>(
        `/skills/pool/${encodeURIComponent(skillName)}/tags`,
        {
          method: "PUT",
          body: JSON.stringify(tags),
        },
      ),

    updatePoolSkillAutoUpdate: (
      skillName: string,
      payload: { enabled: boolean; targets: string[] | null },
    ) =>
      request<{
        updated: boolean;
        enabled: boolean;
        targets: string[] | null;
        sync?: { results?: Array<{ results: SkillTargetResult[] }> };
      }>(`/skills/pool/${encodeURIComponent(skillName)}/auto-update`, {
        method: "PUT",
        body: JSON.stringify(payload),
      }),

    streamOptimizeSkill: async function (
      content: string,
      onChunk: (text: string) => void,
      signal: AbortSignal,
      language: string = "en",
    ): Promise<void> {
      scope.assert();
      const apiUrl = getStreamApiUrl();

      const response = await fetch(`${apiUrl}/skills/ai/optimize/stream`, {
        method: "POST",
        headers: {
          ...buildAuthHeaders(),
          "X-Agent-Id": scope.agentId,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ content, language }),
        signal: skillRequestOptions(scope, { signal }).signal,
      });
      scope.assert();

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
          scope.assert();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");

          for (let i = 0; i < lines.length - 1; i++) {
            const line = lines[i].trim();
            if (line.startsWith("data: ")) {
              const data = line.slice(6);
              let parsed: { text?: string; error?: string; done?: boolean };
              try {
                parsed = JSON.parse(data);
              } catch {
                // Ignore malformed chunks, but propagate valid business errors.
                continue;
              }
              if (parsed.error) throw new Error(parsed.error);
              if (parsed.text) onChunk(parsed.text);
              if (parsed.done) return;
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
}

// Capture identity for every unbound call; pages bind once per scope instead.
export const skillApi = new Proxy({} as ReturnType<typeof createSkillApi>, {
  get:
    (_target, property: keyof ReturnType<typeof createSkillApi>) =>
    (...args: unknown[]) => {
      const agent =
        property === "listSkills" || property === "refreshSkills"
          ? args[0]
          : property === "getSkill"
          ? args[1]
          : undefined;
      const api = createSkillApi(
        captureSkillScope(typeof agent === "string" ? agent : undefined),
      );
      return (api[property] as (...values: unknown[]) => unknown)(...args);
    },
  // Enumerating exports must not read stores while authStore is initializing.
  ownKeys: () => Object.keys(createSkillApi({} as SkillScope)),
  getOwnPropertyDescriptor: () => ({ enumerable: true, configurable: true }),
});
