import { request } from "../request";
import { buildAuthHeaders } from "../authHeaders";

function projectHeaders(chatId?: string): Record<string, string> {
  return {
    ...buildAuthHeaders(),
    ...(chatId ? { "X-Chat-Id": chatId } : {}),
  };
}

export interface GitChangedFile {
  path: string;
  status: string;
  staged: boolean;
}

export interface GitStatus {
  branch: string;
  changes: GitChangedFile[];
  ahead: number;
  behind: number;
}

export interface BranchInfo {
  name: string;
  current: boolean;
  remote: boolean;
}

export interface CommitInfo {
  hash: string;
  author: string;
  date: string;
  message: string;
}

export const gitApi = {
  status: (chatId?: string) =>
    request<GitStatus>("/workspace/git/status", {
      headers: projectHeaders(chatId),
    }),

  branches: (chatId?: string) =>
    request<BranchInfo[]>("/workspace/git/branches", {
      headers: projectHeaders(chatId),
    }),

  checkout: (branch: string, create = false, chatId?: string) =>
    request<{ branch: string }>("/workspace/git/checkout", {
      method: "POST",
      headers: projectHeaders(chatId),
      body: JSON.stringify({ branch, create }),
    }),

  diff: (path?: string, staged = false, untracked = false, chatId?: string) => {
    const params = new URLSearchParams();
    if (path) params.set("path", path);
    if (staged) params.set("staged", "true");
    if (untracked) params.set("untracked", "true");
    return request<{ diff: string }>(
      `/workspace/git/diff?${params.toString()}`,
      { headers: projectHeaders(chatId) },
    );
  },

  stage: (paths: string[] = [], chatId?: string) =>
    request<{ staged: string[] }>("/workspace/git/stage", {
      method: "POST",
      headers: projectHeaders(chatId),
      body: JSON.stringify({ paths }),
    }),

  unstage: (paths: string[] = [], chatId?: string) =>
    request<{ unstaged: string[] }>("/workspace/git/unstage", {
      method: "POST",
      headers: projectHeaders(chatId),
      body: JSON.stringify({ paths }),
    }),

  commit: (message: string, chatId?: string) =>
    request<{ committed: boolean; output: string }>("/workspace/git/commit", {
      method: "POST",
      headers: projectHeaders(chatId),
      body: JSON.stringify({ message }),
    }),

  log: (limit = 20, chatId?: string) =>
    request<CommitInfo[]>(`/workspace/git/log?limit=${limit}`, {
      headers: projectHeaders(chatId),
    }),

  /** Discard unstaged working-directory changes for the given paths (or all). */
  discard: (paths: string[] = [], chatId?: string) =>
    request<{ discarded: string[] }>("/workspace/git/discard", {
      method: "POST",
      headers: projectHeaders(chatId),
      body: JSON.stringify({ paths }),
    }),

  /** Get the unified diff introduced by a specific commit hash. */
  commitDiff: (hash: string, chatId?: string) =>
    request<{ diff: string; hash: string }>(
      `/workspace/git/commit-diff?commit_hash=${encodeURIComponent(hash)}`,
      { headers: projectHeaders(chatId) },
    ),

  /** Revert a commit by hash (creates a new revert commit). */
  revert: (hash: string, chatId?: string) =>
    request<{ reverted: string; output: string }>("/workspace/git/revert", {
      method: "POST",
      headers: projectHeaders(chatId),
      body: JSON.stringify({ commit_hash: hash }),
    }),
};
