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
