import { create } from "zustand";
import type {
  CreatorEvent,
  SpecialistRunView,
  TaskView,
} from "@/contracts/creator";
import { cancelTask, listSpecialistRuns, listTasks } from "@/api/creator";

interface CreatorTaskViewState {
  projectId: string | null;
  runs: SpecialistRunView[];
  tasks: TaskView[];
  loading: boolean;
  error: string | null;
  refresh: (projectId: string) => Promise<void>;
  consumeEvent: (event: CreatorEvent) => void;
  cancel: (taskId: string) => Promise<void>;
  reset: () => void;
}

// Every refresh reads two independently durable collections. Multiple SSE
// lifecycle events can start overlapping reads, so a slower, older snapshot
// must never replace the result of a newer refresh (for example, restoring a
// WAITING_AUTHORIZATION run after SUCCEEDED has already been observed).
let refreshGeneration = 0;

export const useCreatorTaskViewStore = create<CreatorTaskViewState>(
  (set, get) => ({
    projectId: null,
    runs: [],
    tasks: [],
    loading: false,
    error: null,
    refresh: async (projectId) => {
      const generation = ++refreshGeneration;
      set({ projectId, loading: true, error: null });
      try {
        const [runs, tasks] = await Promise.all([
          listSpecialistRuns(projectId),
          listTasks(projectId),
        ]);
        if (generation !== refreshGeneration || get().projectId !== projectId)
          return;
        set({ runs: runs.items, tasks: tasks.items, loading: false });
      } catch (error) {
        if (generation !== refreshGeneration || get().projectId !== projectId)
          return;
        set({ loading: false, error: (error as Error).message });
        throw error;
      }
    },
    consumeEvent: (event) => {
      if (event.projectId !== get().projectId) return;
      const run = event.data.run as SpecialistRunView | undefined;
      const task = event.data.task as TaskView | undefined;
      if (run)
        set((state) => ({
          runs: [run, ...state.runs.filter((item) => item.id !== run.id)],
        }));
      if (task)
        set((state) => ({
          tasks: [task, ...state.tasks.filter((item) => item.id !== task.id)],
        }));
    },
    cancel: async (taskId) => {
      const initialProjectId = get().projectId;
      if (!initialProjectId) return;
      const updated = await cancelTask(initialProjectId, taskId);
      set((state) =>
        state.projectId === initialProjectId
          ? {
              tasks: state.tasks.map((item) =>
                item.id === taskId ? updated : item,
              ),
            }
          : {},
      );
    },
    reset: () => {
      refreshGeneration += 1;
      set({
        projectId: null,
        runs: [],
        tasks: [],
        loading: false,
        error: null,
      });
    },
  }),
);
