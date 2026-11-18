import { request } from "../../api/request";
import type { FilesWorkspaceScope } from "../files-workspace/filesWorkspaceScope";
import { getPendingProjectDirectory } from "../project-directory/pendingProjectDirectory";

export type TerminalScope = Extract<FilesWorkspaceScope, { kind: "session" }>;
export interface TerminalInfo {
  id: string;
  title: string;
  cwd: string;
  exited: boolean;
  exit_code: number | null;
}
export interface TerminalOutput {
  data: string;
  cursor: number;
  reset: boolean;
  exited: boolean;
  exit_code: number | null;
}

export function terminalApi(scope: TerminalScope, group: string) {
  const base = `/terminals/${encodeURIComponent(group)}`;
  const headers: Record<string, string> = { "X-Agent-Id": scope.agentId };
  if (scope.chatId) headers["X-Chat-Id"] = scope.chatId;
  else if (scope.projectDirOverride)
    headers["X-Session-Project-Dir"] = scope.projectDirOverride;
  return {
    list: (signal?: AbortSignal) =>
      request<TerminalInfo[]>(base, { headers, signal }),
    create: () => {
      if (!scope.chatId && scope.sessionId !== "new") {
        return Promise.reject(
          new Error("Wait for the conversation to finish loading"),
        );
      }
      const createHeaders = { ...headers };
      if (!scope.chatId) {
        const pending = getPendingProjectDirectory(
          scope.agentId,
          scope.sessionId,
        );
        if (pending) createHeaders["X-Session-Project-Dir"] = pending;
        else delete createHeaders["X-Session-Project-Dir"];
      }
      return request<TerminalInfo>(base, {
        method: "POST",
        headers: createHeaders,
      });
    },
    close: (id: string) =>
      request(`${base}/${id}`, { method: "DELETE", headers }),
    rename: (id: string, title: string) =>
      request<TerminalInfo>(`${base}/${id}`, {
        method: "PATCH",
        headers,
        body: JSON.stringify({ title }),
      }),
    output: (id: string, after: number, signal: AbortSignal) =>
      request<TerminalOutput>(`${base}/${id}/output?after=${after}`, {
        headers,
        signal,
        timeout: 25000,
      }),
    input: (id: string, data: string) =>
      request(`${base}/${id}/input`, {
        method: "POST",
        headers,
        body: JSON.stringify({ data }),
      }),
    resize: (id: string, rows: number, cols: number) =>
      request(`${base}/${id}/resize`, {
        method: "POST",
        headers,
        body: JSON.stringify({ rows, cols }),
      }),
  };
}

export type TerminalApi = ReturnType<typeof terminalApi>;
