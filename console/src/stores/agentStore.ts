import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { AgentSummary } from "../api/types/agents";

/**
 * Storage key used by both sessionStorage (per-tab state) and localStorage
 * (cross-tab shared state).
 */
const STORAGE_KEY = "qwenpaw-agent-storage";

/**
 * localStorage key that remembers the last-used agent across browser sessions.
 * New tabs read this to set their initial selectedAgent.
 */
const LAST_USED_AGENT_KEY = "qwenpaw-last-used-agent";

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

/**
 * Determines the initial selectedAgent for this tab.
 *
 * Priority:
 *  1. sessionStorage (returning to a tab that already picked an agent)
 *  2. localStorage lastUsedAgent (new tab inherits the most recent choice)
 *  3. "default"
 */
function getInitialSelectedAgent(): string {
  // 1. sessionStorage: returning to a tab that already picked an agent
  try {
    const sessionValue = sessionStorage.getItem(STORAGE_KEY);
    if (sessionValue) {
      const parsed = JSON.parse(sessionValue);
      const agent = parsed?.state?.selectedAgent;
      if (agent) return agent;
    }
  } catch {
    /* ignore */
  }
  // 2. Dedicated localStorage key (written by setSelectedAgent)
  try {
    const lastUsed = localStorage.getItem(LAST_USED_AGENT_KEY);
    if (lastUsed) return lastUsed;
  } catch {
    /* ignore */
  }
  // 3. Shared localStorage state (written by persist middleware)
  try {
    const shared = localStorage.getItem(STORAGE_KEY);
    if (shared) {
      const parsed = JSON.parse(shared);
      const agent = parsed?.state?.selectedAgent;
      if (agent) return agent;
    }
  } catch {
    /* ignore */
  }
  return "default";
}

export const useAgentStore = create<AgentStore>()(
  persist(
    (set, get) => ({
      selectedAgent: getInitialSelectedAgent(),
      agents: [],
      lastChatIdByAgent: {},

      setSelectedAgent: (agentId) => {
        set({ selectedAgent: agentId });
        // Persist to localStorage so new tabs inherit this choice
        try {
          localStorage.setItem(LAST_USED_AGENT_KEY, agentId);
        } catch {
          /* ignore */
        }
      },

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
      name: STORAGE_KEY,
      storage: {
        getItem: (name) => {
          try {
            // Read per-tab state from sessionStorage
            const value = sessionStorage.getItem(name);
            if (value) return JSON.parse(value);
          } catch {
            /* ignore */
          }
          // Fall back to localStorage for shared data (agents list, etc.)
          try {
            const shared = localStorage.getItem(name);
            return shared ? JSON.parse(shared) : null;
          } catch (error) {
            console.error(`Failed to parse agent storage "${name}":`, error);
            localStorage.removeItem(name);
            return null;
          }
        },
        setItem: (name, value) => {
          try {
            // Per-tab state (includes selectedAgent)
            sessionStorage.setItem(name, JSON.stringify(value));
          } catch {
            /* ignore */
          }
          try {
            // Shared state (agents list, lastChatIdByAgent)
            localStorage.setItem(name, JSON.stringify(value));
          } catch (error) {
            console.error(`Failed to save agent storage "${name}":`, error);
          }
        },
        removeItem: (name) => {
          sessionStorage.removeItem(name);
          localStorage.removeItem(name);
        },
      },
    },
  ),
);
