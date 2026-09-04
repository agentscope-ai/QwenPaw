import { create } from "zustand";
import { useAgentStore } from "./agentStore";
import type { AdvisorModeState } from "../api/modules/advisorMode";

interface AdvisorModeStoreState {
  /**
   * Advisor Mode state per agentId. Key absent → not yet fetched from the
   * backend (UI should treat as loading).
   */
  advisorModeByAgent: Record<string, AdvisorModeState>;
  /** Monotonic local-write version used to ignore stale sync responses. */
  advisorModeRevisionByAgent: Record<string, number>;
  setAdvisorMode: (agentId: string, state: AdvisorModeState) => void;
}

// Backend (agent.json) is the source of truth. State is held in-memory
// only and refilled on every app boot via useSyncAdvisorMode — see
// MainLayout. Persisting here would let stale browser cache mask the real
// backend state across tabs / sessions.
export const useAdvisorModeStore = create<AdvisorModeStoreState>((set) => ({
  advisorModeByAgent: {},
  advisorModeRevisionByAgent: {},

  setAdvisorMode: (agentId: string, state: AdvisorModeState) =>
    set((prev: AdvisorModeStoreState) => ({
      advisorModeByAgent: { ...prev.advisorModeByAgent, [agentId]: state },
      advisorModeRevisionByAgent: {
        ...prev.advisorModeRevisionByAgent,
        [agentId]: (prev.advisorModeRevisionByAgent[agentId] ?? 0) + 1,
      },
    })),
}));

/** Safe defaults until the backend state arrives (or when GET fails). */
export const DISABLED_ADVISOR_MODE: AdvisorModeState = {
  enabled: false,
  plan_enabled: true,
  followup_enabled: true,
  on_demand_enabled: true,
  max_consults: 32,
  intervention: {
    consecutive_failures: 3,
    window_size: 10,
    window_failures: 4,
    cooldown_steps: 0,
    max_interventions: 3,
  },
  advisor_thinking: "off",
  agent_id: "",
  advisor_model: null,
  advisor_source: "global",
  worker_model: null,
  worker_source: "main_model",
  advisor_model_override: null,
  worker_model_override: null,
  main_model: null,
  subagent_model: null,
};

/** Convenience hook: Advisor Mode state for the currently selected agent. */
export function useAdvisorMode(): {
  state: AdvisorModeState;
  setAdvisorMode: (state: AdvisorModeState) => void;
} {
  const { selectedAgent } = useAgentStore();
  const { advisorModeByAgent, setAdvisorMode } = useAdvisorModeStore();
  return {
    state: advisorModeByAgent[selectedAgent] ?? DISABLED_ADVISOR_MODE,
    setAdvisorMode: (next: AdvisorModeState) =>
      setAdvisorMode(selectedAgent, next),
  };
}
