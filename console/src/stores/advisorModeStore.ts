import { create } from "zustand";
import { useAgentStore } from "./agentStore";
import type { AdvisorModeState as AdvisorModeApiState } from "../api/modules/advisorMode";

export type AdvisorModeSnapshot = Pick<
  AdvisorModeApiState,
  | "enabled"
  | "plan_enabled"
  | "followup_enabled"
  | "on_demand_enabled"
  | "advisor_model"
  | "worker_model"
> &
  Partial<
    Pick<
      AdvisorModeApiState,
      | "max_consults"
      | "intervention"
      | "advisor_thinking"
      | "advisor_source"
      | "worker_source"
      | "advisor_model_override"
      | "worker_model_override"
      | "main_model"
      | "subagent_model"
    >
  >;

interface AdvisorModeStoreState {
  /**
   * Advisor Mode state per agentId. Key absent → not yet fetched from the
   * backend (UI should treat as loading).
   */
  advisorModeByAgent: Record<string, AdvisorModeSnapshot>;
  /** Monotonic local-write version used to ignore stale sync responses. */
  advisorModeRevisionByAgent: Record<string, number>;
  setAdvisorMode: (agentId: string, state: AdvisorModeSnapshot) => void;
}

// Backend (agent.json) is the source of truth. State is held in-memory
// only and refilled on every app boot via useSyncAdvisorMode — see
// MainLayout. Persisting here would let stale browser cache mask the real
// backend state across tabs / sessions.
export const useAdvisorModeStore = create<AdvisorModeStoreState>((set) => ({
  advisorModeByAgent: {},
  advisorModeRevisionByAgent: {},

  setAdvisorMode: (agentId: string, state: AdvisorModeSnapshot) =>
    set((prev: AdvisorModeStoreState) => ({
      advisorModeByAgent: { ...prev.advisorModeByAgent, [agentId]: state },
      advisorModeRevisionByAgent: {
        ...prev.advisorModeRevisionByAgent,
        [agentId]: (prev.advisorModeRevisionByAgent[agentId] ?? 0) + 1,
      },
    })),
}));

const DISABLED: AdvisorModeSnapshot = {
  enabled: false,
  plan_enabled: true,
  followup_enabled: true,
  on_demand_enabled: true,
  advisor_model: null,
  worker_model: null,
};

/** Convenience hook: Advisor Mode status for the currently selected agent. */
export function useAdvisorMode(): {
  advisorMode: boolean;
  state: AdvisorModeSnapshot;
  initialized: boolean;
  setAdvisorMode: (state: AdvisorModeSnapshot) => void;
} {
  const { selectedAgent } = useAgentStore();
  const { advisorModeByAgent, setAdvisorMode } = useAdvisorModeStore();
  const state = advisorModeByAgent[selectedAgent] ?? DISABLED;
  return {
    advisorMode: state.enabled,
    state,
    initialized: selectedAgent in advisorModeByAgent,
    setAdvisorMode: (next: AdvisorModeSnapshot) =>
      setAdvisorMode(selectedAgent, next),
  };
}
