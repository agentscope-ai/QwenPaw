import { request } from "../request";
import { getApiUrl } from "../config";
import { buildAuthHeaders } from "../authHeaders";

export interface CodingProjectInfo {
  path: string;
  name: string;
  is_workspace_default: boolean;
  exists?: boolean;
}

export interface FsEntry {
  name: string;
  is_dir: boolean;
  is_git: boolean;
}

export interface FsBrowseResult {
  path: string;
  parent: string | null;
  entries: FsEntry[];
}

export interface ProjectListItem {
  path: string;
  name: string;
  is_git: boolean;
  is_active: boolean;
}

export const codingProjectApi = {
  /** Get the current active coding project. */
  get: () => request<CodingProjectInfo>("/workspace/coding-project"),

  /**
   * Set the active coding project.
   * Pass `path: null` to reset to the default workspace.
   */
  set: (path: string | null) =>
    request<CodingProjectInfo>("/workspace/coding-project", {
      method: "PUT",
      body: JSON.stringify({ path }),
    }),

  /** Create a new empty project directory and git init it. */
  create: (name: string) =>
    request<{ path: string; name: string }>("/workspace/coding-project/create", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),

  /** List all coding projects under the agent's coding_projects/ directory. */
  list: () => request<ProjectListItem[]>("/workspace/coding-project/list"),

  /**
   * Clone a Git repository.
   * Returns the URL of the SSE stream – caller reads progress events.
   */
  getCloneUrl: () => getApiUrl("/workspace/coding-project/clone"),

  /** Browse local filesystem directories (for the folder picker UI). */
  browse: (path = "~") =>
    request<FsBrowseResult>(
      `/workspace/coding-project/browse?path=${encodeURIComponent(path)}`,
    ),

  /** Low-level: POST to clone endpoint and return a ReadableStream of SSE. */
  cloneStream: (url: string, name?: string): Promise<Response> =>
    fetch(getApiUrl("/workspace/coding-project/clone"), {
      method: "POST",
      headers: {
        ...buildAuthHeaders(),
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ url, name: name || undefined }),
    }),
};
