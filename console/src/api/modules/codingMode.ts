import { request } from "../request";
import {
  withAgentRequestContext,
  type AgentRequestContext,
} from "./agentRequestContext";

export interface CodingModeState {
  enabled: boolean;
  agent_id: string;
}

export interface CodingModeToggleResponse {
  enabled: boolean;
  agent_id: string;
}

export const codingModeApi = {
  /** Read the mode-independent Coding tools capability state. */
  get: (context?: AgentRequestContext) => {
    const options = withAgentRequestContext(undefined, context);
    return options
      ? request<CodingModeState>("/coding-mode", options)
      : request<CodingModeState>("/coding-mode");
  },

  /** Enable or disable Coding Mode; backend reloads the agent. */
  toggle: (enabled: boolean, context?: AgentRequestContext) =>
    request<CodingModeToggleResponse>(
      "/coding-mode",
      withAgentRequestContext(
        {
          method: "POST",
          body: JSON.stringify({ enabled }),
        },
        context,
      ),
    ),
};
