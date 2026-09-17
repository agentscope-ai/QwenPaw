import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { AgentSummary } from "../api/types/agents";
import { agentsApi } from "../api/modules/agents";
import { menuRegistry } from "../plugins/registry/store";
import { getUserScopedStorageKey } from "./identityStorage";

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

/** Returns true for temporary local session ids like 1785114733908-0l0jmai. */
const isLocalTimestamp = (id: string): boolean => /^\d+-[a-z0-9]+$/.test(id);

let agentRefreshPromise: Promise<void> | null = null;

function persistLastUsedAgent(agentId: string): void {
  try {
    const storageKey = getUserScopedStorageKey(LAST_USED_AGENT_KEY);
    if (agentId) {
      localStorage.setItem(storageKey, agentId);
    } else {
      localStorage.removeItem(storageKey);
    }
  } catch {
    /* ignore */
  }
}

export function pickAccessibleAgentId(
  agents: AgentSummary[],
  selectedAgent: string,
): string {
  const current = agents.find(
    (agent) => agent.id === selectedAgent && agent.enabled,
  );
  return current?.id ?? agents.find((agent) => agent.enabled)?.id ?? "";
}

export function isAgentHistoricalReadOnly(
  agents: AgentSummary[],
  agentId: string,
): boolean {
  return Boolean(
    agents.find((agent) => agent.id === agentId)?.historical_read_only,
  );
}

interface AgentStore {
  selectedAgent: string;
  agents: AgentSummary[];
  /** Per-agent last active chat ID for restoring on agent switch */
  lastChatIdByAgent: Record<string, string>;
  setSelectedAgent: (agentId: string) => void;
  setAgents: (agents: AgentSummary[]) => void;
  refreshAgents: () => Promise<void>;
  addAgent: (agent: AgentSummary) => void;
  removeAgent: (agentId: string) => void;
  updateAgent: (agentId: string, updates: Partial<AgentSummary>) => void;
  setLastChatId: (agentId: string, chatId: string) => void;
  removeLastChatId: (agentId: string) => void;
  getLastChatId: (agentId: string) => string | undefined;
  resetIdentityState: () => void;
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
    const sessionValue = sessionStorage.getItem(
      getUserScopedStorageKey(STORAGE_KEY),
    );
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
    const lastUsed = localStorage.getItem(
      getUserScopedStorageKey(LAST_USED_AGENT_KEY),
    );
    if (lastUsed) return lastUsed;
  } catch {
    /* ignore */
  }
  // 3. Shared localStorage state (written by persist middleware)
  try {
    const shared = localStorage.getItem(getUserScopedStorageKey(STORAGE_KEY));
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
        menuRegistry.refresh();
        persistLastUsedAgent(agentId);
      },

      setAgents: (agents) => set({ agents }),

      refreshAgents: async () => {
        if (agentRefreshPromise !== null) {
          return agentRefreshPromise;
        }

        agentRefreshPromise = agentsApi.listAgents().then((response) => {
          const previousSelection = get().selectedAgent;
          const selectedAgent = pickAccessibleAgentId(
            response.agents,
            previousSelection,
          );
          set({ agents: response.agents, selectedAgent });
          if (selectedAgent !== previousSelection) {
            persistLastUsedAgent(selectedAgent);
            menuRegistry.refresh();
          }
        });
        try {
          await agentRefreshPromise;
        } finally {
          agentRefreshPromise = null;
        }
      },

      addAgent: (agent) =>
        set((state) => ({
          agents: [...state.agents, agent],
        })),

      removeAgent: (agentId) => {
        const shouldRefresh = get().selectedAgent === agentId;
        set((state) => {
          const agents = state.agents.filter((a) => a.id !== agentId);
          const remainingChatIds = { ...state.lastChatIdByAgent };
          delete remainingChatIds[agentId];
          const selectedAgent = shouldRefresh
            ? pickAccessibleAgentId(agents, "")
            : state.selectedAgent;
          if (shouldRefresh) persistLastUsedAgent(selectedAgent);
          return {
            agents,
            lastChatIdByAgent: remainingChatIds,
            selectedAgent,
          };
        });
        if (shouldRefresh) menuRegistry.refresh();
      },

      updateAgent: (agentId, updates) =>
        set((state) => ({
          agents: state.agents.map((a) =>
            a.id === agentId ? { ...a, ...updates } : a,
          ),
        })),

      setLastChatId: (agentId, chatId) => {
        // Never persist a temporary local timestamp id. These ids only exist
        // in memory before the first message is sent and should not be
        // restored on agent switch.
        if (isLocalTimestamp(chatId)) {
          set((state) => {
            const remainingChatIds = { ...state.lastChatIdByAgent };
            delete remainingChatIds[agentId];
            return { lastChatIdByAgent: remainingChatIds };
          });
          return;
        }
        set((state) => ({
          lastChatIdByAgent: { ...state.lastChatIdByAgent, [agentId]: chatId },
        }));
      },

      removeLastChatId: (agentId) =>
        set((state) => {
          const remainingChatIds = { ...state.lastChatIdByAgent };
          delete remainingChatIds[agentId];
          return { lastChatIdByAgent: remainingChatIds };
        }),

      getLastChatId: (agentId) => get().lastChatIdByAgent[agentId],

      resetIdentityState: () => {
        set({
          selectedAgent: "default",
          agents: [],
          lastChatIdByAgent: {},
        });
        menuRegistry.refresh();
      },
    }),
    {
      name: STORAGE_KEY,
      storage: {
        getItem: (name) => {
          const storageKey = getUserScopedStorageKey(name);
          try {
            // Read per-tab state from sessionStorage
            const value = sessionStorage.getItem(storageKey);
            if (value) return JSON.parse(value);
          } catch {
            /* ignore */
          }
          // Fall back to localStorage for shared data (agents list, etc.)
          try {
            const shared = localStorage.getItem(storageKey);
            return shared ? JSON.parse(shared) : null;
          } catch (error) {
            console.error(
              `Failed to parse agent storage "${storageKey}":`,
              error,
            );
            localStorage.removeItem(storageKey);
            return null;
          }
        },
        setItem: (name, value) => {
          const storageKey = getUserScopedStorageKey(name);
          try {
            // Per-tab state (includes selectedAgent)
            sessionStorage.setItem(storageKey, JSON.stringify(value));
          } catch {
            /* ignore */
          }
          try {
            // Shared state (agents list, lastChatIdByAgent)
            localStorage.setItem(storageKey, JSON.stringify(value));
          } catch (error) {
            console.error(
              `Failed to save agent storage "${storageKey}":`,
              error,
            );
          }
        },
        removeItem: (name) => {
          const storageKey = getUserScopedStorageKey(name);
          sessionStorage.removeItem(storageKey);
          localStorage.removeItem(storageKey);
        },
      },
    },
  ),
);
