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
  /**
   * Whether this entry is the agent's own workspace directory.
   *
   * Decided by the server from filesystem identity, because the client
   * cannot: comparing the two paths as text splits one directory into two
   * roots on a case-sensitive volume — two switcher entries, two sets of
   * editor tabs — and merges two distinct ones on a folding volume.
   */
  is_workspace: boolean;
}

/** Effective project-directory list for a chat, plus provenance. */
export interface ChatProjectDirs {
  project_dirs: ProjectDirEntry[];
  source: ChatProjectDirSource;
  agent_project_dir: string | null;
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
  setProjectDirs: (chatId: string, entries: ProjectDirPayloadEntry[]) =>
    request<ChatProjectDirs>(
      `/chats/${encodeURIComponent(chatId)}/project-dirs`,
      {
        method: "PUT",
        body: JSON.stringify({ project_dirs: entries }),
      },
    ),

  /** Clear the chat's override so it inherits the agent default. */
  clearProjectDirs: (chatId: string) =>
    request<ChatProjectDirs>(
      `/chats/${encodeURIComponent(chatId)}/project-dirs`,
      { method: "DELETE" },
    ),

  /**
   * Primary directory only. Still used where a single path is enough (the
   * Files workspace and navigator), and as the fallback display value when
   * the chat has no override and the plural list comes back empty.
   */
  get: (chatId: string) =>
    request<EffectiveProjectDirectory>(
      `/chats/${encodeURIComponent(chatId)}/project-dir`,
    ),
};
