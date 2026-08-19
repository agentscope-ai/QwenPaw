import { create } from "zustand";

import { dispatchWorkGraphNode, getWorkGraph } from "@/api/creator/workGraph";
import type { WorkGraphView } from "@/contracts/creator/workGraph";

interface WorkGraphState {
  projectId: string | null;
  graph: WorkGraphView | null;
  loading: boolean;
  error: string | null;
  dispatching: Record<string, boolean>;
  refresh: (projectId: string) => Promise<void>;
  dispatchNode: (projectId: string, nodeId: string) => Promise<void>;
  reset: () => void;
}

// SSE lifecycle events can trigger overlapping refreshes; an older, slower
// snapshot must never replace a newer one (same latest-wins discipline as
// creatorTaskViewStore).
let refreshGeneration = 0;

export const useWorkGraphStore = create<WorkGraphState>((set, get) => ({
  projectId: null,
  graph: null,
  loading: false,
  error: null,
  dispatching: {},
  refresh: async (projectId) => {
    const generation = ++refreshGeneration;
    set((state) =>
      state.projectId === projectId
        ? { loading: true }
        : {
            projectId,
            graph: null,
            loading: true,
            error: null,
            dispatching: {},
          },
    );
    try {
      const graph = await getWorkGraph(projectId);
      if (generation !== refreshGeneration) return;
      set({ projectId, graph, loading: false, error: null });
    } catch (error) {
      if (generation !== refreshGeneration) return;
      set({
        loading: false,
        error: (error as Error).message || "work graph load failed",
      });
    }
  },
  dispatchNode: async (projectId, nodeId) => {
    set((state) => ({
      dispatching: { ...state.dispatching, [nodeId]: true },
    }));
    try {
      await dispatchWorkGraphNode(projectId, nodeId);
    } finally {
      set((state) => {
        const next = { ...state.dispatching };
        delete next[nodeId];
        return { dispatching: next };
      });
      void get().refresh(projectId);
    }
  },
  reset: () =>
    set({
      projectId: null,
      graph: null,
      loading: false,
      error: null,
      dispatching: {},
    }),
}));
