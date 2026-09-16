export type FilesWorkspaceScope =
  | {
      kind: "agent";
      agentId: string;
    }
  | {
      kind: "session";
      agentId: string;
      sessionId: string;
      chatId?: string;
      projectDirOverride?: string;
    };

export type MemoryScope = "public" | "private";

export type MemoryScopeSummary = {
  scope: MemoryScope;
  can_read: boolean;
  can_edit: boolean;
  status: "active" | "access_revoked" | "cleanup_pending";
  index_state:
    | "ready"
    | "needs_reindex"
    | "reindexing"
    | "reindex_failed"
    | "unavailable";
  index_version: number;
};

export function resolveMemoryScopeSelection(
  scopes: MemoryScopeSummary[],
  current?: MemoryScope,
): MemoryScope {
  if (current && scopes.some((item) => item.scope === current)) return current;
  return scopes.some((item) => item.scope === "private") ? "private" : "public";
}

export function filesWorkspaceScopeKey(scope: FilesWorkspaceScope): string {
  if (scope.kind === "agent") {
    return `agent:${scope.agentId}`;
  }
  return `session:${scope.agentId}:${scope.sessionId}`;
}

export function agentFilesScopeKey(agentId: string): string {
  return filesWorkspaceScopeKey({ kind: "agent", agentId });
}

export function sessionFilesScopeKey(
  agentId: string,
  sessionId: string,
): string {
  return filesWorkspaceScopeKey({
    kind: "session",
    agentId,
    sessionId,
  });
}
