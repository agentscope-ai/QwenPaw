import { beforeEach, describe, expect, it } from "vitest";
import {
  selectTasksForSession,
  useBackgroundTasksStore,
} from "./backgroundTasksStore";

function resetStore() {
  useBackgroundTasksStore.setState({ tasks: [] });
}

describe("backgroundTasksStore", () => {
  beforeEach(() => {
    resetStore();
  });

  it("addTask is idempotent per toolCallId", () => {
    const store = useBackgroundTasksStore.getState();
    store.addTask({
      toolCallId: "tc-1",
      toolName: "shell",
      sessionId: "sid-a",
      startTime: 1000,
    });
    store.addTask({
      toolCallId: "tc-1",
      toolName: "shell",
      sessionId: "sid-a",
      startTime: 2000,
    });
    expect(useBackgroundTasksStore.getState().tasks).toHaveLength(1);
    expect(useBackgroundTasksStore.getState().tasks[0].startTime).toBe(1000);
  });

  it("selectTasksForSession filters by session and excludes empty-session tasks", () => {
    const store = useBackgroundTasksStore.getState();
    store.addTask({
      toolCallId: "tc-a",
      toolName: "a",
      sessionId: "sid-a",
      startTime: 1,
    });
    store.addTask({
      toolCallId: "tc-b",
      toolName: "b",
      sessionId: "sid-b",
      startTime: 2,
    });
    store.addTask({
      toolCallId: "tc-empty",
      toolName: "e",
      sessionId: "",
      startTime: 3,
    });

    const tasks = useBackgroundTasksStore.getState().tasks;
    const forA = selectTasksForSession(tasks, "sid-a");
    expect(forA.map((t) => t.toolCallId)).toEqual(["tc-a"]);
  });

  it("selectTasksForSession returns empty while sessionId is pending", () => {
    const store = useBackgroundTasksStore.getState();
    store.addTask({
      toolCallId: "tc-a",
      toolName: "a",
      sessionId: "sid-a",
      startTime: 1,
    });
    const tasks = useBackgroundTasksStore.getState().tasks;
    expect(selectTasksForSession(tasks, "")).toEqual([]);
  });

  it("removeTasks drops only requested ids", () => {
    const store = useBackgroundTasksStore.getState();
    store.addTask({
      toolCallId: "tc-1",
      toolName: "a",
      sessionId: "s",
      startTime: 1,
    });
    store.addTask({
      toolCallId: "tc-2",
      toolName: "b",
      sessionId: "s",
      startTime: 2,
    });
    store.removeTasks(["tc-1"]);
    expect(
      useBackgroundTasksStore.getState().tasks.map((t) => t.toolCallId),
    ).toEqual(["tc-2"]);
  });
});
