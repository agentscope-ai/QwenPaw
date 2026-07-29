import { beforeEach, describe, expect, it, vi } from "vitest";
import type {
  SpecialistRunListResponse,
  TaskListResponse,
  TaskView,
} from "@/contracts/creator";
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

    const olderRefresh = useCreatorTaskViewStore.getState().refresh("p1");
    const newerRefresh = useCreatorTaskViewStore.getState().refresh("p1");

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
