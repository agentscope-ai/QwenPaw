import { request } from "../request";

export interface EffectiveProjectDirectory {
  project_dir: string;
  source: "session" | "agent" | "workspace_fallback";
  agent_project_dir: string | null;
  exists: boolean;
}

export const chatProjectDirectoryApi = {
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
