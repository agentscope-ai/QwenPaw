import { request } from "../request";
import { getApiUrl } from "../config";
import { buildAuthHeaders } from "../authHeaders";
import {
  withAgentRequestContext,
  type AgentRequestContext,
} from "./agentRequestContext";

function requestProject<T>(
  path: string,
  context?: AgentRequestContext,
  options?: Parameters<typeof request>[1],
): Promise<T> {
  const merged = withAgentRequestContext(options, context);
  return merged ? request<T>(path, merged) : request<T>(path);
}

function projectFetchHeaders(
  context?: AgentRequestContext,
  headers?: HeadersInit,
): HeadersInit {
  return (
    withAgentRequestContext(
      { headers: { ...buildAuthHeaders(), ...(headers ?? {}) } },
      context,
    )?.headers ?? {}
  );
}

export interface ProjectDirectoryInfo {
  path: string;
  name: string;
  is_workspace_default: boolean;
  workspace_dir?: string;
  project_kind?: "draft" | "published_baseline" | "user_runtime" | "legacy";
  project_key?: string;
  project_read_only?: boolean;
  workspace_kind?: "draft" | "published_baseline" | "user_runtime" | "legacy";
  workspace_key?: string;
  workspace_read_only?: boolean;
  exists?: boolean;
}

export interface ProjectListItem {
  path: string;
  name: string;
  is_git: boolean;
  is_active: boolean;
}

export interface BrowseDirsResponse {
  current: string;
  parent: string | null;
  dirs: Array<{ name: string; path: string }>;
  selectable?: boolean;
}

export const projectDirectoryApi = {
  /** Get the current Agent default project directory. */
  get: (context?: AgentRequestContext) =>
    requestProject<ProjectDirectoryInfo>(
      "/workspace/project-directory",
      context,
    ),

  /**
   * Set the active project directory.
   * Pass `path: null` to reset to the default workspace.
   */
  set: (path: string | null, context?: AgentRequestContext) =>
    requestProject<ProjectDirectoryInfo>(
      "/workspace/project-directory",
      context,
      {
        method: "PUT",
        body: JSON.stringify({ path }),
      },
    ),

  /** Create a new empty project directory and git init it. */
  create: (name: string, context?: AgentRequestContext) =>
    requestProject<{ path: string; name: string }>(
      "/workspace/project-directory/create",
      context,
      {
        method: "POST",
        body: JSON.stringify({ name }),
      },
    ),

  /** List all project directorys under the agent's coding_projects/ directory. */
  list: (context?: AgentRequestContext) =>
    requestProject<ProjectListItem[]>(
      "/workspace/project-directory/list",
      context,
    ),

  /**
   * Copy a local directory into coding_projects/ (excludes node_modules etc.)
   * and set it as the active project.
   */
  importLocal: (path: string, name?: string, context?: AgentRequestContext) =>
    requestProject<{ path: string; name: string }>(
      "/workspace/project-directory/import-local",
      context,
      {
        method: "POST",
        body: JSON.stringify({ path, name: name || undefined }),
      },
    ),

  /**
   * Upload a zip of a project folder; backend extracts it to coding_projects/.
   * Must use fetch directly (not request()) so the browser can set the
   * multipart/form-data Content-Type boundary automatically.
   */
  uploadZip: async (
    zipFile: File,
    name: string,
    context?: AgentRequestContext,
  ): Promise<{ path: string; name: string }> => {
    const formData = new FormData();
    formData.append("file", zipFile);
    const res = await fetch(
      getApiUrl(
        `/workspace/project-directory/upload-zip?name=${encodeURIComponent(
          name,
        )}`,
      ),
      {
        method: "POST",
        // No Content-Type header — browser sets multipart/form-data with boundary
        headers: projectFetchHeaders(context),
        body: formData,
      },
    );
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(text || `Upload failed: ${res.status}`);
    }
    return res.json() as Promise<{ path: string; name: string }>;
  },

  /** Browse directories on the server for the file-browser UI. */
  browseDirs: (
    path?: string,
    showHidden?: boolean,
    context?: AgentRequestContext,
  ) =>
    requestProject<BrowseDirsResponse>(
      `/workspace/project-directory/browse-dirs?path=${encodeURIComponent(
        path || "~",
      )}${showHidden ? "&show_hidden=true" : ""}`,
      context,
    ),

  /** Low-level: POST to clone endpoint and return a ReadableStream of SSE. */
  cloneStream: (
    url: string,
    name?: string,
    context?: AgentRequestContext,
  ): Promise<Response> =>
    fetch(getApiUrl("/workspace/project-directory/clone"), {
      method: "POST",
      headers: projectFetchHeaders(context, {
        "Content-Type": "application/json",
      }),
      body: JSON.stringify({ url, name: name || undefined }),
    }),
};
