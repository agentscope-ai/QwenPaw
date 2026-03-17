import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { AgentSummary } from "../api/types/agents";

interface AgentStore {
  selectedAgent: string;
  agents: AgentSummary[];
  setSelectedAgent: (agentId: string) => void;
  setAgents: (agents: AgentSummary[]) => void;
  addAgent: (agent: AgentSummary) => void;
  removeAgent: (agentId: string) => void;
  updateAgent: (agentId: string, updates: Partial<AgentSummary>) => void;
}

export const useAgentStore = create<AgentStore>()(
  persist(
    (set) => ({
      selectedAgent: "default",
      agents: [],

      setSelectedAgent: (agentId) => set({ selectedAgent: agentId }),

      setAgents: (agents) => set({ agents }),

      addAgent: (agent) =>
        set((state) => ({
          agents: [...state.agents, agent],
        })),

      removeAgent: (agentId) =>
        set((state) => ({
          agents: state.agents.filter((a) => a.id !== agentId),
        })),

      updateAgent: (agentId, updates) =>
        set((state) => ({
          agents: state.agents.map((a) =>
            a.id === agentId ? { ...a, ...updates } : a,
          ),
        })),
    }),
    {
      name: "copaw-agent-storage",
    },
  ),
);
