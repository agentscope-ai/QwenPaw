import { create } from "zustand";
import type {
  CreatorEvent,
  SpecialistRunView,
  TaskView,
} from "@/contracts/creator";
import {
  cancelTask,
  creatorReadSequence,
  listSpecialistRuns,
  listTasks,
} from "@/api/creator";

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
// An in-flight cancellation belongs to this visit, including across polls.
let projectGeneration = 0;

type Row = { id: string; updatedAt?: string; createdAt?: string };
const seenAfterRead = new WeakMap<Row, number>();

function compareRowTime(left: Row, right: Row): number {
  const a = left.updatedAt ?? left.createdAt ?? "";
  const b = right.updatedAt ?? right.createdAt ?? "";
  const ms = Date.parse(a) - Date.parse(b);
  if (!Number.isFinite(ms)) return 0;
  if (ms !== 0) return ms;
  // Date.parse normalizes time zones but discards Python's sub-millisecond digits.
  const fraction = (iso: string) =>
    (iso.match(/\.(\d+)/)?.[1] ?? "").padEnd(6, "0");
  return fraction(a).localeCompare(fraction(b));
}

function mergeSnapshot<T extends Row>(
  request: Promise<unknown>,
  current: T[],
  incoming: T[],
): T[] {
  const start = creatorReadSequence(request);
  const arrivedDuringRead = (row: Row) =>
    (seenAfterRead.get(row) ?? -1) >= start;
  const live = new Map(current.map((row) => [row.id, row]));
  const result = incoming.map((row) => {
    const existing = live.get(row.id);
    live.delete(row.id);
    if (existing) {
      const order = compareRowTime(existing, row);
      if (order > 0 || (order === 0 && arrivedDuringRead(existing)))
        return existing;
    }
    seenAfterRead.set(row, start);
    return row;
  });
  // An authoritative absence can retire rows already seen when the GET started.
  // A row delivered by SSE during that GET must survive until a later read.
  return [...Array.from(live.values()).filter(arrivedDuringRead), ...result];
}

function applyRow<T extends Row>(current: T[], incoming: T): T[] {
  const existing = current.find((row) => row.id === incoming.id);
  if (existing && compareRowTime(existing, incoming) > 0) return current;
  seenAfterRead.set(incoming, creatorReadSequence());
  return [incoming, ...current.filter((row) => row.id !== incoming.id)];
}

// `CreatorEvent.data` is one shared, untyped payload: `task.*` carries a
// TaskView on `task`, while `subagent.accepted` events persisted before the
// backend renamed the brief to `delegationText` carry a raw string there.
// Rows feed a WeakMap, so non-object payloads must never pass.
function asRow<T extends Row>(value: unknown): T | null {
  if (typeof value !== "object" || value === null) return null;
  if (typeof (value as Row).id !== "string") return null;
  return value as T;
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
      const switching = get().projectId !== projectId;
      if (switching) projectGeneration += 1;
      set({
        projectId,
        loading: true,
        error: null,
        ...(switching ? { runs: [], tasks: [] } : {}),
      });
      try {
        const runRequest = listSpecialistRuns(projectId, {}, options);
        const taskRequest = listTasks(projectId, options);
        const [runs, tasks] = await Promise.all([runRequest, taskRequest]);
        if (generation !== refreshGeneration || get().projectId !== projectId)
          return;
        const mergedTasks = mergeSnapshot(
          taskRequest,
          get().tasks,
          tasks.items,
        );
        const mergedRuns = mergeSnapshot(runRequest, get().runs, runs.items);
        set({
          runs: mergedRuns,
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
      const run = asRow<SpecialistRunView>(event.data.run);
      const task = asRow<TaskView>(event.data.task);
      if (run)
        set((state) => ({
          runs: applyRow(state.runs, run),
        }));
      if (task)
        set((state) => ({
          tasks: applyRow(state.tasks, task),
        }));
    },
    cancel: async (taskId) => {
      const initialProjectId = get().projectId;
      if (!initialProjectId) return;
      const generation = projectGeneration;
      const updated = await cancelTask(initialProjectId, taskId);
      if (
        generation !== projectGeneration ||
        get().projectId !== initialProjectId
      )
        return;
      set((state) => {
        const tasks = state.tasks.map((item) => {
          if (item.id !== taskId || compareRowTime(item, updated) > 0)
            return item;
          seenAfterRead.set(updated, creatorReadSequence());
          return updated;
        });
        return { tasks };
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
