import { request } from "../request";

export interface CodingModeState {
  enabled: boolean;
  project_dir: string | null;
  agent_id: string;
}

export interface CodingModeToggleResponse {
  enabled: boolean;
  agent_id: string;
}

export const codingModeApi = {
  /** Read Coding Mode state (enabled + project_dir) from agent.json. */
  get: () => request<CodingModeState>("/coding-mode"),

  /** Enable or disable Coding Mode; backend reloads the agent. */
  toggle: (enabled: boolean) =>
    request<CodingModeToggleResponse>("/coding-mode", {
      method: "POST",
      body: JSON.stringify({ enabled }),
    }),
};
