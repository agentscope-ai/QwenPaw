import { beforeEach, describe, expect, it, vi } from "vitest";
import type {
  SpecialistRunListResponse,
  TaskListResponse,
  TaskView,
} from "@/contracts/creator";
import { useCreatorTaskViewStore } from "@/store/creatorTaskViewStore";
import { ev } from "@/test/sessionEventBuilders";
import { makeRun } from "@/test/agentFixtures";

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

  it.each([
    { taskStatus: "CANCELLED", delegated: false, expected: "CANCELLED" },
    { taskStatus: "RUNNING", delegated: false, expected: "WAITING_RUNTIME" },
    { taskStatus: "CANCELLED", delegated: true, expected: "WAITING_RUNTIME" },
  ] as const)(
    "reconciles cancelled media without hiding live Tasks or chat delegations: %j",
    async ({ taskStatus, delegated, expected }) => {
      const run = makeRun({
        status: "WAITING_RUNTIME",
        taskRefs: ["task-1"],
        metadata: {
          commandType: "GENERATE_STORYBOARD_IMAGE",
          ...(delegated ? { parentActionId: "delegate-action" } : {}),
        },
      });
      const task: TaskView = {
        id: "task-1",
        projectId: "p1",
        transactionId: null,
        specialistRunId: run.id,
        kind: "image_generation",
        targetRef: "element:one",
        status: taskStatus,
        progress: null,
        resultRefs: [],
      };
      vi.stubGlobal(
        "fetch",
        vi.fn(async (url: string) =>
          response({
            items: url.endsWith("/tasks") ? [task] : [run],
          }),
        ),
      );
      await useCreatorTaskViewStore.getState().refresh("p1");
      expect(useCreatorTaskViewStore.getState().runs[0].status).toBe(expected);
    },
  );

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

  it("preserves newer live rows across a slow poll and older events", async () => {
    const pending = deferred<Response>();
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) =>
        String(input).endsWith("/tasks")
          ? pending.promise
          : Promise.resolve(response({ items: [] })),
      ),
    );
    const stale: TaskView = {
      id: "t1",
      projectId: "p1",
      transactionId: null,
      specialistRunId: null,
      kind: "compose",
      targetRef: "project:p1",
      status: "QUEUED",
      progress: null,
      resultRefs: [],
      updatedAt: "2026-10-20T12:00:00Z",
    };
    const terminal: TaskView = {
      ...stale,
      status: "SUCCEEDED",
      updatedAt: "2026-10-20T12:01:00Z",
    };
    const legacy = { ...stale, id: "t2", updatedAt: undefined };
    const store = useCreatorTaskViewStore.getState();
    const poll = store.refresh("p1");
    store.consumeEvent(ev(3, "task.updated", { task: terminal }));
    store.consumeEvent(ev(4, "task.updated", { task: legacy }));
    pending.resolve(response({ items: [stale] }));
    await poll;
    store.consumeEvent(ev(2, "task.updated", { task: stale }));
    expect(useCreatorTaskViewStore.getState().tasks).toEqual([
      legacy,
      terminal,
    ]);
  });

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
});
