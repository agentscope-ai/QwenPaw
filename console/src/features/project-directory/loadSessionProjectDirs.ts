/**
 * The one place that answers "which directories is this session bound to?".
 *
 * Three sources have to be tried in order, and both the picker panel and the
 * Files navigator need the same answer — a session that reads them in a
 * different order would show a directory list the tools do not actually use.
 */
import {
  chatProjectDirectoryApi,
  type ChatProjectDirSource,
  type ProjectDirEntry,
} from "../../api/modules/chatProjectDirectory";
import { projectDirectoryApi } from "../../api/modules/projectDirectory";
import { getPendingProjectDirs } from "./pendingProjectDirectory";

export interface SessionProjectDirsSnapshot {
  /** Effective list, primary first. Never empty. */
  dirs: ProjectDirEntry[];
  source: ChatProjectDirSource;
  agentProjectDir: string | null;
}

/** A directory the client picked but the server has not confirmed yet. */
function pendingEntry(path: string, label: string | null): ProjectDirEntry {
  // `exists: true` because the pick came from the server-side browser, which
  // only lists real directories. Claiming "missing" here would flag a
  // perfectly good directory before the first message validates it.
  // `is_workspace: false` because a pick made in the directory browser is a
  // project directory, and the only consumer of the flag — the Files
  // switcher — has no extra roots to collapse on a chat this new anyway.
  return { path, label, exists: true, nested_with: null, is_workspace: false };
}

/**
 * Resolve the session's bound directories: the chat's persisted list, else the
 * pending pick a brand-new chat holds locally, else the agent default.
 *
 * The returned list always has at least one entry. When nothing is configured
 * that entry is the agent workspace (with `source: "workspace_fallback"`), so
 * callers can render a directory rather than an empty panel — the rest of the
 * console resolves relative paths there too.
 */
export async function loadSessionProjectDirs(
  agentId: string,
  sessionId: string,
  chatId?: string,
): Promise<SessionProjectDirsSnapshot> {
  if (chatId) {
    const next = await chatProjectDirectoryApi.getProjectDirs(chatId);
    if (next.project_dirs.length > 0) {
      return {
        dirs: next.project_dirs,
        source: next.source,
        agentProjectDir: next.agent_project_dir,
      };
    }
    // Nothing bound (workspace fallback): the plural endpoint reports an empty
    // list, so fall back to the singular view for the directory to display.
    const single = await chatProjectDirectoryApi.get(chatId);
    return {
      dirs: [
        {
          path: single.project_dir,
          label: null,
          exists: single.exists,
          nested_with: null,
          // The plural endpoint reported nothing bound, which means the
          // primary *is* the workspace — that is what the fallback resolves
          // to, so the flag is known here without asking again.
          is_workspace: true,
        },
      ],
      source: next.source,
      agentProjectDir: next.agent_project_dir,
    };
  }

  // Brand-new chat: no server id yet, so the pick lives in sessionStorage.
  const pending = getPendingProjectDirs(agentId, sessionId);
  if (pending) {
    return {
      dirs: pending.dirs.map((entry) => pendingEntry(entry.path, entry.label)),
      source: "session",
      agentProjectDir: null,
    };
  }

  // Nothing pending: the agent default is the starting point.
  const next = await projectDirectoryApi.get();
  return {
    dirs: [
      {
        path: next.path,
        label: null,
        exists: next.exists ?? true,
        nested_with: null,
        // The agent default either is the workspace or is a directory of its
        // own, and this endpoint already says which — no path comparison.
        is_workspace: next.is_workspace_default,
      },
    ],
    source: next.is_workspace_default ? "workspace_fallback" : "agent",
    agentProjectDir: next.is_workspace_default ? null : next.path,
  };
}
