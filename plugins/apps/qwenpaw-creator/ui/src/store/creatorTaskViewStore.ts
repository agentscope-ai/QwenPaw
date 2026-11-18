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
  refresh: (projectId: string, options?: { dedupe?: boolean }) => Promise<void>;
  consumeEvent: (event: CreatorEvent) => void;
  cancel: (taskId: string) => Promise<void>;
  reset: () => void;
}

// Every refresh reads two independently durable collections. Multiple SSE
// lifecycle events can start overlapping reads, so a slower, older snapshot
// must never replace the result of a newer refresh (for example, restoring a
// WAITING_AUTHORIZATION run after SUCCEEDED has already been observed).
let refreshGeneration = 0;
let projectGeneration = 0;

interface UpdatedRow {
  id: string;
  updatedAt?: string;
}

function timestampDifference(
  incoming: UpdatedRow,
  previous: UpdatedRow,
): number {
  return (
    Date.parse(incoming.updatedAt ?? "") - Date.parse(previous.updatedAt ?? "")
  );
}

function applyEvent<T extends UpdatedRow>(current: T[], incoming: T): T[] {
  const previous = current.find((row) => row.id === incoming.id);
  if (previous && timestampDifference(incoming, previous) < 0) return current;
  return [incoming, ...current.filter((row) => row.id !== incoming.id)];
}

function mergeSnapshot<T extends UpdatedRow>(
  incoming: T[],
  initial: T[],
  current: T[],
): T[] {
  const beforeRequest = new Map(initial.map((row) => [row.id, row]));
  const observed = new Map(current.map((row) => [row.id, row]));
  const snapshot = incoming.map((row) => {
    const latest = observed.get(row.id);
    if (!latest) return row;
    observed.delete(row.id);
    const age = timestampDifference(row, latest);
    // Rows from legacy servers can lack timestamps. An event observed during
    // this request wins unless the snapshot is demonstrably newer.
    if (age < 0 || (latest !== beforeRequest.get(row.id) && !(age > 0)))
      return latest;
    return row;
  });
  // Preserve events for rows created while this request was in flight.
  const arrived = [...observed.values()].filter(
    (row) => row !== beforeRequest.get(row.id),
  );
  return [...arrived, ...snapshot];
}

function reconcileCancelledMediaRuns(
  runs: SpecialistRunView[],
  tasks: TaskView[],
): SpecialistRunView[] {
  const byId = new Map(tasks.map((task) => [task.id, task]));
  return runs.map((run) => {
    // A media executor cannot continue once all its Tasks are cancelled.
    // Task and Run heads can arrive in separate polls (or from older servers
    // that omitted Run cleanup). Chat delegations may handle a cancelled
    // child tool and continue, so their own terminal event stays authoritative.
    if (
      !run.metadata?.commandType ||
      run.metadata.parentActionId ||
      ![
        "QUEUED",
        "QUEUED_CAPACITY",
        "RUNNING_MODEL",
        "WAITING_RUNTIME",
        "WAITING_AUTHORIZATION",
      ].includes(run.status) ||
      run.taskRefs.length === 0 ||
      !run.taskRefs.every((id) => {
        const task = byId.get(id);
        return task?.specialistRunId === run.id && task.status === "CANCELLED";
      })
    )
      return run;
    return { ...run, status: "CANCELLED" };
  });
}

export const useCreatorTaskViewStore = create<CreatorTaskViewState>(
  (set, get) => ({
    projectId: null,
    runs: [],
    tasks: [],
    loading: false,
    error: null,
    refresh: async (projectId, options) => {
      const generation = ++refreshGeneration;
      if (get().projectId !== projectId) {
        projectGeneration++;
        set({ projectId, tasks: [], runs: [] });
      }
      const initial = get();
      set({ loading: true, error: null });
      try {
        const [runs, tasks] = await Promise.all([
          listSpecialistRuns(projectId, {}, options),
          listTasks(projectId, options),
        ]);
        if (generation !== refreshGeneration || get().projectId !== projectId)
          return;
        const current = get();
        const mergedTasks = mergeSnapshot(
          tasks.items,
          initial.tasks,
          current.tasks,
        );
        const mergedRuns = mergeSnapshot(
          runs.items,
          initial.runs,
          current.runs,
        );
        set({
          runs: reconcileCancelledMediaRuns(mergedRuns, mergedTasks),
          tasks: mergedTasks,
          loading: false,
        });
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
      if (run || task)
        set((state) => {
          const tasks = task ? applyEvent(state.tasks, task) : state.tasks;
          const runs = run ? applyEvent(state.runs, run) : state.runs;
          return { tasks, runs: reconcileCancelledMediaRuns(runs, tasks) };
        });
    },
    cancel: async (taskId) => {
      const initialProjectId = get().projectId;
      if (!initialProjectId) return;
      const generation = projectGeneration;
      const updated = await cancelTask(initialProjectId, taskId);
      set((state) => {
        if (
          generation !== projectGeneration ||
          state.projectId !== initialProjectId
        )
          return {};
        const tasks = applyEvent(state.tasks, updated);
        return { tasks, runs: reconcileCancelledMediaRuns(state.runs, tasks) };
      });
    },
    reset: () => {
      refreshGeneration += 1;
      projectGeneration += 1;
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
