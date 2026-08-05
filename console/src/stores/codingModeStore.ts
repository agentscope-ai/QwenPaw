import { create } from "zustand";
import { useAgentStore } from "./agentStore";

interface CodingModeState {
  /**
   * Whether Coding Mode is active per agentId. Key absent → not yet
   * fetched from backend (UI should treat as loading).
   */
  codingModeByAgent: Record<string, boolean>;
  /** Monotonic local-write version used to ignore stale sync responses. */
  codingModeRevisionByAgent: Record<string, number>;
  setCodingMode: (agentId: string, enabled: boolean) => void;
}

// Backend (agent.json) is the source of truth. State is held in-memory
// only and refilled on every app boot via useSyncCodingMode — see
// MainLayout. Persisting here would let stale browser cache mask the
// real backend state across tabs / sessions.
export const useCodingModeStore = create<CodingModeState>((set) => ({
  codingModeByAgent: {},
  codingModeRevisionByAgent: {},

  setCodingMode: (agentId: string, enabled: boolean) =>
    set((state: CodingModeState) => ({
      codingModeByAgent: { ...state.codingModeByAgent, [agentId]: enabled },
      codingModeRevisionByAgent: {
        ...state.codingModeRevisionByAgent,
        [agentId]: (state.codingModeRevisionByAgent[agentId] ?? 0) + 1,
      },
    })),
}));

/** Convenience hook: coding mode status for the currently selected agent.
 *
 * `initialized` is true once useSyncCodingMode has populated the store
 * for the selected agent — gate route decisions on it to avoid the
 * "default = false → flash chat → fetch resolves → page mismatch" bug.
 */
export function useCodingMode(): {
  codingMode: boolean;
  initialized: boolean;
  setCodingMode: (enabled: boolean) => void;
} {
  const { selectedAgent } = useAgentStore();
  const { codingModeByAgent, setCodingMode } = useCodingModeStore();
  return {
    codingMode: codingModeByAgent[selectedAgent] ?? false,
    initialized: selectedAgent in codingModeByAgent,
    setCodingMode: (enabled: boolean) => setCodingMode(selectedAgent, enabled),
  };
}
