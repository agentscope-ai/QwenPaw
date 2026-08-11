import { request } from "../request";

/**
 * Provenance of a chat's effective project directory / directory list.
 *
 * - "session": this chat has its own override.
 * - "agent": inherited from the agent default.
 * - "workspace_fallback": nothing configured; the agent workspace is used.
 * - "fork": inherited from a fork source and locked.
 * - "active_mode": inherited from the active mode and locked.
 * - "request": supplied per-request and locked.
 * - "inherited": inherited from a parent and locked.
 */
export type ChatProjectDirSource =
  | "session"
  | "agent"
  | "workspace_fallback"
  | "fork"
  | "active_mode"
  | "request"
  | "inherited";

export interface EffectiveProjectDirectory {
  project_dir: string;
  source: ChatProjectDirSource;
  agent_project_dir: string | null;
  exists: boolean;
}

/** One effective project-directory entry as returned by the server. */
export interface ProjectDirEntry {
  path: string;
  label: string | null;
  exists: boolean;
  nested_with: string | null;
}

/** Effective project-directory list for a chat, plus provenance. */
export interface ChatProjectDirs {
  project_dirs: ProjectDirEntry[];
  source: ChatProjectDirSource;
  agent_project_dir: string | null;
  project_name: string | null;
  project_name_is_custom: boolean;
}

/** One entry as sent to the server when setting the list. */
export interface ProjectDirPayloadEntry {
  path: string;
  label?: string | null;
}

export const chatProjectDirectoryApi = {
  // ── Plural (session-scoped ordered list) ──────────────────────────────
  /** Get the chat's effective project-directory list, primary first. */
  getProjectDirs: (chatId: string) =>
    request<ChatProjectDirs>(
      `/chats/${encodeURIComponent(chatId)}/project-dirs`,
    ),

  /**
   * Replace the chat's whole project-directory list. The payload is the
   * full ordered list (index 0 becomes primary); add/remove/make-primary
   * are all expressed as list transforms followed by one PUT.
   */
  setProjectDirs: (
    chatId: string,
    entries: ProjectDirPayloadEntry[],
    projectName?: string | null,
  ) =>
    request<ChatProjectDirs>(
      `/chats/${encodeURIComponent(chatId)}/project-dirs`,
      {
        method: "PUT",
        body: JSON.stringify({
          project_dirs: entries,
          project_name: projectName ?? null,
        }),
      },
    ),

  /** Clear the chat's override so it inherits the agent default. */
  clearProjectDirs: (chatId: string) =>
    request<ChatProjectDirs>(
      `/chats/${encodeURIComponent(chatId)}/project-dirs`,
      { method: "DELETE" },
    ),

  // ── Singular (deprecated, agent-scope-compatible) ────────────────────
  get: (chatId: string) =>
    request<EffectiveProjectDirectory>(
      `/chats/${encodeURIComponent(chatId)}/project-dir`,
    ),
  set: (chatId: string, projectDir: string) =>
    request<EffectiveProjectDirectory>(
      `/chats/${encodeURIComponent(chatId)}/project-dir`,
      {
        method: "PUT",
        body: JSON.stringify({ project_dir: projectDir }),
      },
    ),
  clear: (chatId: string) =>
    request<EffectiveProjectDirectory>(
      `/chats/${encodeURIComponent(chatId)}/project-dir`,
      { method: "DELETE" },
    ),
};
