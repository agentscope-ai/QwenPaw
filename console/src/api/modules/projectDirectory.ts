import { request } from "../request";
import { getApiUrl } from "../config";
import { buildAuthHeaders } from "../authHeaders";

export interface ProjectDirectoryInfo {
  path: string;
  name: string;
  is_workspace_default: boolean;
  workspace_dir?: string;
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
  get: () => request<ProjectDirectoryInfo>("/workspace/project-directory"),

  /**
   * Set the active project directory.
   * Pass `path: null` to reset to the default workspace.
   */
  set: (path: string | null) =>
    request<ProjectDirectoryInfo>("/workspace/project-directory", {
      method: "PUT",
      body: JSON.stringify({ path }),
    }),

  /** Create a new empty project directory and git init it. */
  create: (name: string) =>
    request<{ path: string; name: string }>(
      "/workspace/project-directory/create",
      {
        method: "POST",
        body: JSON.stringify({ name }),
      },
    ),

  /** List all project directorys under the agent's coding_projects/ directory. */
  list: () => request<ProjectListItem[]>("/workspace/project-directory/list"),

  /**
   * Copy a local directory into coding_projects/ (excludes node_modules etc.)
   * and set it as the active project.
   */
  importLocal: (path: string, name?: string) =>
    request<{ path: string; name: string }>(
      "/workspace/project-directory/import-local",
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
        headers: buildAuthHeaders(),
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
  browseDirs: (path?: string, showHidden?: boolean) =>
    request<BrowseDirsResponse>(
      `/workspace/project-directory/browse-dirs?path=${encodeURIComponent(
        path || "~",
      )}${showHidden ? "&show_hidden=true" : ""}`,
    ),

  /** Low-level: POST to clone endpoint and return a ReadableStream of SSE. */
  cloneStream: (url: string, name?: string): Promise<Response> =>
    fetch(getApiUrl("/workspace/project-directory/clone"), {
      method: "POST",
      headers: {
        ...buildAuthHeaders(),
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ url, name: name || undefined }),
    }),
};
