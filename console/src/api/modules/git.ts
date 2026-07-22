import { request } from "../request";

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
  status: () => request<GitStatus>("/workspace/git/status"),

  branches: () => request<BranchInfo[]>("/workspace/git/branches"),

  checkout: (branch: string, create = false) =>
    request<{ branch: string }>("/workspace/git/checkout", {
      method: "POST",
      body: JSON.stringify({ branch, create }),
    }),

  diff: (path?: string, staged = false, untracked = false) => {
    const params = new URLSearchParams();
    if (path) params.set("path", path);
    if (staged) params.set("staged", "true");
    if (untracked) params.set("untracked", "true");
    return request<{ diff: string }>(
      `/workspace/git/diff?${params.toString()}`,
    );
  },

  stage: (paths: string[] = []) =>
    request<{ staged: string[] }>("/workspace/git/stage", {
      method: "POST",
      body: JSON.stringify({ paths }),
    }),

  unstage: (paths: string[] = []) =>
    request<{ unstaged: string[] }>("/workspace/git/unstage", {
      method: "POST",
      body: JSON.stringify({ paths }),
    }),

  commit: (message: string) =>
    request<{ committed: boolean; output: string }>("/workspace/git/commit", {
      method: "POST",
      body: JSON.stringify({ message }),
    }),

  log: (limit = 20) =>
    request<CommitInfo[]>(`/workspace/git/log?limit=${limit}`),

  /** Discard unstaged working-directory changes for the given paths (or all). */
  discard: (paths: string[] = []) =>
    request<{ discarded: string[] }>("/workspace/git/discard", {
      method: "POST",
      body: JSON.stringify({ paths }),
    }),

  /** Get the unified diff introduced by a specific commit hash. */
  commitDiff: (hash: string) =>
    request<{ diff: string; hash: string }>(
      `/workspace/git/commit-diff?commit_hash=${encodeURIComponent(hash)}`,
    ),

  /** Revert a commit by hash (creates a new revert commit). */
  revert: (hash: string) =>
    request<{ reverted: string; output: string }>("/workspace/git/revert", {
      method: "POST",
      body: JSON.stringify({ commit_hash: hash }),
    }),
};
