import { request } from "../request";
import type { ModelSlotConfig } from "../types";

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
  /** The worker model actually used. null means the agent keeps the primary model. */
  worker_model: ModelSlotConfig | null;
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
  /** A slot sets the override, `null` clears it and an omitted field is unchanged. */
  advisor_model?: ModelSlotConfig | null;
  worker_model?: ModelSlotConfig | null;
}

export type Slot = ModelSlotConfig | null | undefined;

/** `provider:model`, or "" for the default slot. */
export function slotKey(slot: Slot): string {
  return slot ? `${slot.provider_id}:${slot.model}` : "";
}

export function slotLabel(slot: Slot): string {
  return slot ? `${slot.provider_id} / ${slot.model}` : "";
}

export const advisorModeApi = {
  /** Read Advisor Mode state for the current agent. */
  get: () => request<AdvisorModeState>("/advisor-mode"),

  /** Update Advisor Mode. Fields left out are unchanged. */
  update: (body: AdvisorModeUpdate) =>
    request<AdvisorModeState>("/advisor-mode", {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
