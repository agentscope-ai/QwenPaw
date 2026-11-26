import { beforeEach, describe, expect, it, vi } from "vitest";
import type {
  SpecialistRunListResponse,
  TaskListResponse,
  TaskView,
} from "@/contracts/creator";
import { listTasks } from "@/api/creator";
import { ev } from "@/test/sessionEventBuilders";
import { useCreatorTaskViewStore } from "@/store/creatorTaskViewStore";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function response<T>(body: T): Response {
  return {
    ok: true,
    status: 200,
    json: async () => body,
  } as Response;
}

describe("creator task view refresh ordering", () => {
  beforeEach(() => {
    useCreatorTaskViewStore.getState().reset();
  });

  it("keeps a task admitted during a shared GET, then accepts a later authoritative absence", async () => {
    const pending = deferred<Response>();
    const fetchMock = vi.fn((input: RequestInfo | URL) =>
      String(input).endsWith("/tasks")
        ? pending.promise
        : Promise.resolve(response({ items: [] })),
    );
    vi.stubGlobal("fetch", fetchMock);
    const store = useCreatorTaskViewStore.getState();
    useCreatorTaskViewStore.setState({ projectId: "p1" });
    // The first caller can be outside this store. The later refreshes must use
    // the actual task GET's boundary even when the run GET starts later.
    const first = listTasks("p1");
    store.consumeEvent(
      ev(1, "task.created", {
        task: { id: "t1", projectId: "p1", status: "RUNNING" },
      }),
    );
    const joined = store.refresh("p1");
    pending.resolve(response({ items: [] }));
    await Promise.all([first, joined, store.refresh("p1")]);
    expect(
      fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/tasks")),
    ).toHaveLength(1);
    expect(
      useCreatorTaskViewStore.getState().tasks.map((task) => task.id),
    ).toEqual(["t1"]);
    await store.refresh("p1");
    expect(useCreatorTaskViewStore.getState().tasks).toEqual([]);
  });

  it("retains a task from an independent read when a later caller joins an older GET", async () => {
    const slow = deferred<Response>();
    const task = { id: "new-task", status: "RUNNING" };
    let taskReads = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        if (!String(input).endsWith("/tasks"))
          return Promise.resolve(response({ items: [] }));
        return ++taskReads === 1
          ? slow.promise
          : Promise.resolve(response({ items: [task] }));
      }),
    );
    const first = listTasks("p1");
    const store = useCreatorTaskViewStore.getState();
    await store.refresh("p1", { dedupe: false });
    const joined = store.refresh("p1");
    slow.resolve(response({ items: [] }));
    await Promise.all([first, joined]);
    expect(taskReads).toBe(2);
    expect(useCreatorTaskViewStore.getState().tasks).toEqual([task]);
  });

  it("orders events within a millisecond across UTC offsets", () => {
    useCreatorTaskViewStore.setState({ projectId: "p1" });
    const store = useCreatorTaskViewStore.getState();
    const apply = (seq: number, status: string, updatedAt: string) =>
      store.consumeEvent(
        ev(seq, "task.updated", {
          task: { id: "t1", projectId: "p1", status, updatedAt },
        }),
      );
    apply(1, "SUCCEEDED", "2026-10-01T09:00:01.123999+00:00");
    apply(2, "RUNNING", "2026-10-01T17:00:01.123001+08:00");
    expect(useCreatorTaskViewStore.getState().tasks[0].status).toBe(
      "SUCCEEDED",
    );
    apply(3, "CANCELLED", "2026-10-01T17:00:01.124000+08:00");
    expect(useCreatorTaskViewStore.getState().tasks[0].status).toBe(
      "CANCELLED",
    );
  });

  it("does not let an older pending snapshot overwrite a newer terminal refresh", async () => {
    const oldRuns = deferred<Response>();
    const oldTasks = deferred<Response>();
    const newRuns = deferred<Response>();
    const newTasks = deferred<Response>();
    const runResponses = [oldRuns, newRuns];
    const taskResponses = [oldTasks, newTasks];
    let runRequest = 0;
    let taskRequest = 0;

    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/specialist-runs"))
          return runResponses[runRequest++].promise;
        if (url.endsWith("/tasks")) return taskResponses[taskRequest++].promise;
        throw new Error(`Unexpected request: ${url}`);
      }),
    );

    // dedupe: false because this case needs two genuinely separate responses
    // to arrive out of order. Production cannot produce that shape -- two
    // overlapping reads of one path are served by one shared request now --
    // but refreshes seconds apart still race, which is what the generation
    // guard below protects.
    const olderRefresh = useCreatorTaskViewStore
      .getState()
      .refresh("p1", { dedupe: false });
    const newerRefresh = useCreatorTaskViewStore
      .getState()
      .refresh("p1", { dedupe: false });

    const terminalRuns: SpecialistRunListResponse = {
      items: [
        {
          id: "run-1",
          role: "ai_editing_director",
          displayName: "一致性质检 Agent",
          status: "SUCCEEDED",
          targetRefs: ["project:p1"],
          finalMarker: "SUCCESS",
          finalSummaryText: "质检完成。",
          taskRefs: [],
          metadata: {},
        },
      ],
    };
    const terminalTasks: TaskListResponse = { items: [] };
    newRuns.resolve(response(terminalRuns));
    newTasks.resolve(response(terminalTasks));
    await newerRefresh;
    expect(useCreatorTaskViewStore.getState().runs[0].status).toBe("SUCCEEDED");

    const staleRuns: SpecialistRunListResponse = {
      items: [
        {
          ...terminalRuns.items[0],
          status: "WAITING_AUTHORIZATION",
          finalMarker: undefined,
        },
      ],
    };
    oldRuns.resolve(response(staleRuns));
    oldTasks.resolve(response({ items: [] } satisfies TaskListResponse));
    await olderRefresh;

    expect(useCreatorTaskViewStore.getState().runs[0]).toMatchObject({
      id: "run-1",
      status: "SUCCEEDED",
      finalMarker: "SUCCESS",
    });
    expect(useCreatorTaskViewStore.getState().loading).toBe(false);
  });

  it.each([
    { scenario: "reopened project", expected: "RUNNING" },
    { scenario: "newer task update", expected: "SUCCEEDED" },
    { scenario: "same project polled", expected: "CANCELLED" },
  ])(
    "applies a delayed cancellation to the correct task state: $scenario",
    async ({ scenario, expected }) => {
      const cancelled = deferred<Response>();
      const task = {
        id: "t1",
        projectId: "p1",
        status: "RUNNING",
        updatedAt: "2026-10-01T09:00:01.100Z",
      };
      vi.stubGlobal(
        "fetch",
        vi.fn((url: string) => {
          if (url.endsWith("/cancel")) return cancelled.promise;
          const items = url.endsWith("/p1/tasks") ? [task] : [];
          return Promise.resolve(response({ items }));
        }),
      );
      const store = useCreatorTaskViewStore.getState();
      await store.refresh("p1");
      const pending = store.cancel("t1");
      if (scenario === "reopened project") {
        await store.refresh("p2");
        await store.refresh("p1");
      } else if (scenario === "newer task update") {
        store.consumeEvent(
          ev(1, "task.updated", {
            task: {
              ...task,
              status: "SUCCEEDED",
              updatedAt: "2026-10-01T09:00:01.300Z",
            },
          }),
        );
      } else {
        // Polling the same project preserves its in-flight user action.
        await store.refresh("p1");
      }
      cancelled.resolve(
        response({
          ...task,
          status: "CANCELLED",
          updatedAt: "2026-10-01T09:00:01.200Z",
        }),
      );
      await pending;
      expect(useCreatorTaskViewStore.getState().tasks[0].status).toBe(expected);
    },
  );

  it("drops a cancel response after switching projects", async () => {
    const cancelled = deferred<Response>();
    vi.stubGlobal(
      "fetch",
      vi.fn(() => cancelled.promise),
    );
    const task = (projectId: string, status: TaskView["status"]): TaskView => ({
      id: "reused-task-id",
      projectId,
      transactionId: null,
      specialistRunId: null,
      kind: "compose",
      targetRef: `project:${projectId}`,
      status,
      progress: null,
      resultRefs: [],
    });
    useCreatorTaskViewStore.setState({
      projectId: "p1",
      tasks: [task("p1", "RUNNING")],
    });

    const cancel = useCreatorTaskViewStore.getState().cancel("reused-task-id");
    useCreatorTaskViewStore.setState({
      projectId: "p2",
      tasks: [task("p2", "RUNNING")],
    });
    cancelled.resolve(response(task("p1", "CANCELLED")));
    await cancel;

    expect(useCreatorTaskViewStore.getState()).toMatchObject({
      projectId: "p2",
      tasks: [task("p2", "RUNNING")],
    });
  });

  it("ignores the string delegation brief that subagent.accepted carries on `task`", () => {
    const existing: TaskView = {
      id: "t1",
      projectId: "p1",
      transactionId: null,
      specialistRunId: null,
      kind: "compose",
      targetRef: "project:p1",
      status: "RUNNING",
      progress: null,
      resultRefs: [],
    };
    useCreatorTaskViewStore.setState({ projectId: "p1", tasks: [existing] });
    const store = useCreatorTaskViewStore.getState();
    // Replayed history written before the backend renamed the field keeps the
    // brief under `task`; a WeakMap keyed by rows must never see a string.
    expect(() =>
      store.consumeEvent(
        ev(1, "subagent.accepted", {
          runId: "run-1",
          role: "source_intelligence_agent",
          task: "分析这段小猫视角影片（cat_camera_1.mp4）",
        }),
      ),
    ).not.toThrow();
    expect(useCreatorTaskViewStore.getState().tasks).toEqual([existing]);
    expect(useCreatorTaskViewStore.getState().runs).toEqual([]);
  });
});
