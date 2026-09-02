import { request } from "../request";
import type { ModelSlotConfig } from "../types";

/** Where an effective advisor/agent model comes from. */
export type AdvisorSource = "override" | "main_model" | "global";
export type WorkerSource = "override" | "subagent_model" | "main_model";

/** Thresholds of the mid-run auto intervention. */
export interface AdvisorInterventionConfig {
  consecutive_failures: number;
  window_size: number;
  window_failures: number;
  cooldown_steps: number;
  max_interventions: number;
}

export type AdvisorThinking = "inherit" | "off" | "low" | "medium" | "high";

export interface AdvisorModeState {
  enabled: boolean;
  /** Whether the advisor writes a plan before the agent's first step. */
  plan_enabled: boolean;
  followup_enabled: boolean;
  /** Whether the agent may call the consult_advisor tool on its own. */
  on_demand_enabled: boolean;
  /** Cap on the agent's own consult_advisor calls per conversation. */
  max_consults: number;
  intervention: AdvisorInterventionConfig;
  /** Thinking level of the advisor's own calls. */
  advisor_thinking: AdvisorThinking;
  agent_id: string;
  /** The advisor model actually used. */
  advisor_model: ModelSlotConfig | null;
  advisor_source: AdvisorSource;
  /** The worker model actually used; null = the agent keeps the main model. */
  worker_model: ModelSlotConfig | null;
  worker_source: WorkerSource;
  /** Overrides stored in agent.json (null = default slot). */
  advisor_model_override: ModelSlotConfig | null;
  worker_model_override: ModelSlotConfig | null;
  /** The defaults the overrides fall back to, for labels. */
  main_model: ModelSlotConfig | null;
  subagent_model: ModelSlotConfig | null;
}

export interface AdvisorModeUpdate {
  enabled?: boolean;
  plan_enabled?: boolean;
  followup_enabled?: boolean;
  on_demand_enabled?: boolean;
  max_consults?: number;
  /** Fields left out keep their value. */
  intervention?: Partial<AdvisorInterventionConfig>;
  advisor_thinking?: AdvisorThinking;
  /** A slot sets the override; `null` clears it; omitted = unchanged. */
  advisor_model?: ModelSlotConfig | null;
  worker_model?: ModelSlotConfig | null;
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
