import { request } from "../request";
import type { ModelSlotConfig } from "../types";

export interface AdvisorModeState {
  enabled: boolean;
  /** Whether the advisor writes a plan before the agent's first step. */
  plan_enabled: boolean;
  followup_enabled: boolean;
  /** Whether the agent may call the consult_advisor tool on its own. */
  on_demand_enabled: boolean;
  agent_id: string;
  /** The advisor ("teacher") — the agent's main model. */
  teacher_model: ModelSlotConfig | null;
  /** The agent ("student") — the sub-agent model, or null when it keeps the main model. */
  student_model: ModelSlotConfig | null;
}

export interface AdvisorModeUpdate {
  enabled?: boolean;
  plan_enabled?: boolean;
  followup_enabled?: boolean;
  on_demand_enabled?: boolean;
}

export const advisorModeApi = {
  /** Read Advisor Mode state for the current agent. */
  get: () => request<AdvisorModeState>("/advisor-mode"),

  /** Update Advisor Mode; fields left out are unchanged. */
  update: (body: AdvisorModeUpdate) =>
    request<AdvisorModeState>("/advisor-mode", {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
