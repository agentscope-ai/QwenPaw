import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { AgentSummary } from "../api/types/agents";

interface AgentStore {
  selectedAgent: string;
  agents: AgentSummary[];
  /** Per-agent last active chat ID for restoring on agent switch */
  lastChatIdByAgent: Record<string, string>;
  setSelectedAgent: (agentId: string) => void;
  setAgents: (agents: AgentSummary[]) => void;
  addAgent: (agent: AgentSummary) => void;
  removeAgent: (agentId: string) => void;
  updateAgent: (agentId: string, updates: Partial<AgentSummary>) => void;
  setLastChatId: (agentId: string, chatId: string) => void;
  getLastChatId: (agentId: string) => string | undefined;
}

export const useAgentStore = create<AgentStore>()(
  persist(
    (set, get) => ({
      selectedAgent: "default",
      agents: [],
      lastChatIdByAgent: {},

      setSelectedAgent: (agentId) => set({ selectedAgent: agentId }),

      setAgents: (agents) => set({ agents }),

      addAgent: (agent) =>
        set((state) => ({
          agents: [...state.agents, agent],
        })),

      removeAgent: (agentId) =>
        set((state) => {
          const { [agentId]: _, ...remainingChatIds } = state.lastChatIdByAgent;
          return {
            agents: state.agents.filter((a) => a.id !== agentId),
            lastChatIdByAgent: remainingChatIds,
            ...(state.selectedAgent === agentId
              ? { selectedAgent: "default" }
              : {}),
          };
        }),

      updateAgent: (agentId, updates) =>
        set((state) => ({
          agents: state.agents.map((a) =>
            a.id === agentId ? { ...a, ...updates } : a,
          ),
        })),

      setLastChatId: (agentId, chatId) =>
        set((state) => ({
          lastChatIdByAgent: { ...state.lastChatIdByAgent, [agentId]: chatId },
        })),

      getLastChatId: (agentId) => get().lastChatIdByAgent[agentId],
    }),
    {
      name: "copaw-agent-storage",
      storage: {
        getItem: (name) => {
          try {
            const value = sessionStorage.getItem(name);
            return value ? JSON.parse(value) : null;
          } catch (error) {
            console.error(`Failed to parse agent storage "${name}":`, error);
            // Remove corrupted data to prevent repeated errors
            sessionStorage.removeItem(name);
            return null;
          }
        },
        setItem: (name, value) => {
          try {
            sessionStorage.setItem(name, JSON.stringify(value));
          } catch (error) {
            console.error(`Failed to save agent storage "${name}":`, error);
          }
        },
        removeItem: (name) => {
          sessionStorage.removeItem(name);
        },
      },
    },
  ),
);
