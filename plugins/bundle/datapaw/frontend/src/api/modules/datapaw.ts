import { request } from "../request";

export type ChatMode = "agent" | "plan";

export const datapawApi = {
  getMode: (agentId: string, sessionId: string, userId = "default") =>
    request<{ mode: ChatMode }>(
      `/agents/${encodeURIComponent(agentId)}/sessions/${encodeURIComponent(sessionId)}/mode?user_id=${encodeURIComponent(userId)}`,
    ),

  setMode: (
    agentId: string,
    sessionId: string,
    mode: ChatMode,
    userId = "default",
  ) =>
    request<{ mode: ChatMode }>(
      `/agents/${encodeURIComponent(agentId)}/sessions/${encodeURIComponent(sessionId)}/mode?user_id=${encodeURIComponent(userId)}`,
      {
        method: "PUT",
        body: JSON.stringify({ mode }),
      },
    ),
};
