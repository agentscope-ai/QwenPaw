/**
 * Background task watcher — SSE/poll dual-leg tracking of offloaded tool
 * calls, user cancel, session-switch teardown, and panel rehydration.
 * Regression family: cross-agent switch isolation (watchers must not leak
 * into other sessions) and cancel-path consistency.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// ---- Hoisted mocks ---------------------------------------------------------

const mocks = vi.hoisted(() => ({
  getOutput: vi.fn(),
  getInfo: vi.fn(),
  cancel: vi.fn(),
  list: vi.fn(),
  subscribe: vi.fn(),
  extractOutputText: vi.fn(),
  resolveBackendSessionId: vi.fn(),
  message: { success: vi.fn(), info: vi.fn(), error: vi.fn() },
}));

vi.mock("antd", () => ({ message: mocks.message }));
vi.mock("../i18n", () => ({
  default: {
    t: (key: string, opts?: { defaultValue?: string }) =>
      opts?.defaultValue ?? key,
  },
}));
vi.mock("../api/modules/toolCalls", () => ({
  toolCallsApi: {
    getOutput: (...a: unknown[]) => mocks.getOutput(...a),
    getInfo: (...a: unknown[]) => mocks.getInfo(...a),
    cancel: (...a: unknown[]) => mocks.cancel(...a),
    list: (...a: unknown[]) => mocks.list(...a),
  },
  subscribeToolCallStream: (...a: unknown[]) => mocks.subscribe(...a),
  extractOutputText: (...a: unknown[]) => mocks.extractOutputText(...a),
}));
vi.mock("../utils/resolveBackendSessionId", () => ({
  resolveBackendSessionId: (...a: unknown[]) =>
    mocks.resolveBackendSessionId(...a),
}));

interface StreamHandlers {
  onChunk: (payload: unknown) => void;
  onDone: () => void;
  onError: () => void;
}

// Mutable holder: the subscribe mock fills `.handlers` when the watcher
// registers, so tests must read `ctl.handlers` AFTER registration.
function makeSubscribe() {
  const ctl: {
    handlers: StreamHandlers | null;
    abort: ReturnType<typeof vi.fn>;
  } = { handlers: null, abort: vi.fn() };
  mocks.subscribe.mockImplementation(
    (_sid: string, _tcid: string, h: StreamHandlers) => {
      ctl.handlers = h;
      return ctl.abort;
    },
  );
  return ctl;
}

async function loadModule() {
  const mod = await import("./useBackgroundTaskWatcher");
  const { useBackgroundTasksStore } = await import(
    "../stores/backgroundTasksStore"
  );
  return { ...mod, useBackgroundTasksStore };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.resetModules();
  mocks.resolveBackendSessionId.mockImplementation(
    (s?: string) => s ?? "sess-1",
  );
  mocks.getOutput.mockResolvedValue({ final_state: "completed" });
  mocks.extractOutputText.mockReturnValue("");
});

afterEach(() => {
  vi.useRealTimers();
});

describe("registerBackgroundTask", () => {
  it("ignores empty tool call ids", async () => {
    const { registerBackgroundTask, useBackgroundTasksStore } =
      await loadModule();
    registerBackgroundTask({ sessionId: "s", toolCallId: "", toolName: "t" });
    expect(useBackgroundTasksStore.getState().tasks).toHaveLength(0);
  });

  it("enqueues the task with resolved session id", async () => {
    const { registerBackgroundTask, useBackgroundTasksStore } =
      await loadModule();
    registerBackgroundTask({
      sessionId: "local-1",
      toolCallId: "tc1",
      toolName: "shell",
      startTime: 123,
    });
    const task = useBackgroundTasksStore.getState().tasks[0];
    expect(task.toolCallId).toBe("tc1");
    expect(task.toolName).toBe("shell");
    expect(task.sessionId).toBe("local-1");
    expect(task.status).toBe("running");
  });

  it("falls back to the tool call id when the name is empty", async () => {
    const { registerBackgroundTask, useBackgroundTasksStore } =
      await loadModule();
    registerBackgroundTask({ sessionId: "s", toolCallId: "tc9", toolName: "" });
    expect(useBackgroundTasksStore.getState().tasks[0].toolName).toBe("tc9");
  });

  it("retries session resolution when it starts empty", async () => {
    vi.useFakeTimers();
    mocks.resolveBackendSessionId
      .mockReturnValueOnce("")
      .mockReturnValue("late-sess");
    const { registerBackgroundTask, useBackgroundTasksStore } =
      await loadModule();
    registerBackgroundTask({ sessionId: "", toolCallId: "tc1", toolName: "t" });
    expect(mocks.subscribe).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(300);
    expect(mocks.subscribe).toHaveBeenCalledWith(
      "late-sess",
      "tc1",
      expect.anything(),
    );
    const task = useBackgroundTasksStore
      .getState()
      .tasks.find((t) => t.toolCallId === "tc1");
    expect(task?.sessionId).toBe("late-sess");
  });

  it("hydrates already-completed tasks immediately", async () => {
    const { registerBackgroundTask, useBackgroundTasksStore } =
      await loadModule();
    registerBackgroundTask({
      sessionId: "s",
      toolCallId: "tc1",
      toolName: "t",
      alreadyCompleted: true,
    });
    await Promise.resolve();
    await Promise.resolve();
    const task = useBackgroundTasksStore
      .getState()
      .tasks.find((t) => t.toolCallId === "tc1");
    expect(task?.status).toBe("done");
    expect(mocks.subscribe).not.toHaveBeenCalled();
  });
});

describe("startBackgroundTaskWatcher", () => {
  it("appends streamed chunks to live output", async () => {
    const { registerBackgroundTask, useBackgroundTasksStore } =
      await loadModule();
    const sub = makeSubscribe();
    registerBackgroundTask({
      sessionId: "s",
      toolCallId: "tc1",
      toolName: "t",
    });
    sub.handlers!.onChunk({ data: "hello " });
    sub.handlers!.onChunk({ data: { text: "world" } });
    sub.handlers!.onChunk({ data: { content: [{ text: "!" }] } });
    const task = useBackgroundTasksStore
      .getState()
      .tasks.find((t) => t.toolCallId === "tc1");
    expect(task?.liveOutput).toBe("hello world!");
  });

  it("finalizes as done with a toast when the stream completes", async () => {
    const { registerBackgroundTask, useBackgroundTasksStore } =
      await loadModule();
    const sub = makeSubscribe();
    mocks.extractOutputText.mockReturnValue("final output");
    registerBackgroundTask({
      sessionId: "s",
      toolCallId: "tc1",
      toolName: "shell",
    });
    sub.handlers!.onDone();
    await Promise.resolve();
    await Promise.resolve();
    const task = useBackgroundTasksStore
      .getState()
      .tasks.find((t) => t.toolCallId === "tc1");
    expect(task?.status).toBe("done");
    expect(task?.result).toBe("final output");
    expect(mocks.message.success).toHaveBeenCalledTimes(1);
  });

  it("marks the task cancelled when final state is interrupted", async () => {
    const { registerBackgroundTask, useBackgroundTasksStore } =
      await loadModule();
    const sub = makeSubscribe();
    mocks.getOutput.mockResolvedValue({ final_state: "interrupted" });
    registerBackgroundTask({
      sessionId: "s",
      toolCallId: "tc1",
      toolName: "t",
    });
    sub.handlers!.onDone();
    await Promise.resolve();
    await Promise.resolve();
    const task = useBackgroundTasksStore
      .getState()
      .tasks.find((t) => t.toolCallId === "tc1");
    expect(task?.status).toBe("cancelled");
    expect(mocks.message.info).toHaveBeenCalledTimes(1);
    expect(mocks.message.success).not.toHaveBeenCalled();
  });

  it("does not double-finalize or double-toast", async () => {
    const { registerBackgroundTask } = await loadModule();
    const sub = makeSubscribe();
    registerBackgroundTask({
      sessionId: "s",
      toolCallId: "tc1",
      toolName: "t",
    });
    sub.handlers!.onDone();
    sub.handlers!.onDone();
    await Promise.resolve();
    await Promise.resolve();
    expect(mocks.message.success).toHaveBeenCalledTimes(1);
    expect(mocks.getOutput).toHaveBeenCalledTimes(1);
  });

  it("is idempotent per tool call id", async () => {
    const { registerBackgroundTask, startBackgroundTaskWatcher } =
      await loadModule();
    makeSubscribe();
    registerBackgroundTask({
      sessionId: "s",
      toolCallId: "tc1",
      toolName: "t",
    });
    startBackgroundTaskWatcher("s", "tc1");
    expect(mocks.subscribe).toHaveBeenCalledTimes(1);
  });

  it("falls back to polling when the stream errors", async () => {
    vi.useFakeTimers();
    const { registerBackgroundTask, useBackgroundTasksStore } =
      await loadModule();
    const sub = makeSubscribe();
    mocks.getInfo.mockResolvedValue({ status: "running" });
    registerBackgroundTask({
      sessionId: "s",
      toolCallId: "tc1",
      toolName: "t",
    });
    sub.handlers!.onError();
    await vi.advanceTimersByTimeAsync(3000);
    expect(mocks.getInfo).toHaveBeenCalledTimes(1);

    mocks.getInfo.mockResolvedValue({ status: "done", end_state: "completed" });
    await vi.advanceTimersByTimeAsync(3000);
    const task = useBackgroundTasksStore
      .getState()
      .tasks.find((t) => t.toolCallId === "tc1");
    expect(task?.status).toBe("done");
  });

  it("treats poll errors as completion (404 after finalize)", async () => {
    vi.useFakeTimers();
    const { registerBackgroundTask, useBackgroundTasksStore } =
      await loadModule();
    const sub = makeSubscribe();
    mocks.getInfo.mockRejectedValue(new Error("404"));
    registerBackgroundTask({
      sessionId: "s",
      toolCallId: "tc1",
      toolName: "t",
    });
    sub.handlers!.onError();
    await vi.advanceTimersByTimeAsync(3000);
    const task = useBackgroundTasksStore
      .getState()
      .tasks.find((t) => t.toolCallId === "tc1");
    expect(task?.status).toBe("done");
  });

  it("marks the poll result cancelled for interrupted end state", async () => {
    vi.useFakeTimers();
    const { registerBackgroundTask, useBackgroundTasksStore } =
      await loadModule();
    const sub = makeSubscribe();
    mocks.getInfo.mockResolvedValue({
      status: "done",
      end_state: "interrupted",
    });
    registerBackgroundTask({
      sessionId: "s",
      toolCallId: "tc1",
      toolName: "t",
    });
    sub.handlers!.onError();
    await vi.advanceTimersByTimeAsync(3000);
    const task = useBackgroundTasksStore
      .getState()
      .tasks.find((t) => t.toolCallId === "tc1");
    expect(task?.status).toBe("cancelled");
  });
});

describe("stopBackgroundTaskWatcher", () => {
  it("aborts the stream without changing task status", async () => {
    const {
      registerBackgroundTask,
      stopBackgroundTaskWatcher,
      useBackgroundTasksStore,
    } = await loadModule();
    const sub = makeSubscribe();
    registerBackgroundTask({
      sessionId: "s",
      toolCallId: "tc1",
      toolName: "t",
    });
    stopBackgroundTaskWatcher("tc1");
    expect(sub.abort).toHaveBeenCalledTimes(1);
    expect(useBackgroundTasksStore.getState().tasks[0].status).toBe("running");
  });
});

describe("cancelBackgroundTask", () => {
  it("rejects a blank session id with an error toast", async () => {
    const { cancelBackgroundTask } = await loadModule();
    await expect(cancelBackgroundTask("  ", "tc1")).rejects.toThrow(
      "Missing backend session id",
    );
    expect(mocks.message.error).toHaveBeenCalledTimes(1);
  });

  it("cancels the task and records live output as the result", async () => {
    const {
      registerBackgroundTask,
      cancelBackgroundTask,
      useBackgroundTasksStore,
    } = await loadModule();
    const sub = makeSubscribe();
    registerBackgroundTask({
      sessionId: "s",
      toolCallId: "tc1",
      toolName: "t",
    });
    sub.handlers!.onChunk({ data: "partial" });
    await cancelBackgroundTask("s", "tc1");
    expect(mocks.cancel).toHaveBeenCalledWith("s", "tc1");
    const task = useBackgroundTasksStore
      .getState()
      .tasks.find((t) => t.toolCallId === "tc1");
    expect(task?.status).toBe("cancelled");
    expect(task?.result).toBe("partial");
  });

  it("resumes the watcher when the cancel API fails", async () => {
    const { registerBackgroundTask, cancelBackgroundTask } = await loadModule();
    const sub = makeSubscribe();
    mocks.cancel.mockRejectedValue(new Error("backend down"));
    registerBackgroundTask({
      sessionId: "s",
      toolCallId: "tc1",
      toolName: "t",
    });
    await expect(cancelBackgroundTask("s", "tc1")).rejects.toThrow(
      "backend down",
    );
    expect(sub.abort).toHaveBeenCalledTimes(1); // first watcher stopped
    expect(mocks.subscribe).toHaveBeenCalledTimes(2); // resumed watcher
    expect(mocks.message.error).toHaveBeenCalledTimes(1);
  });
});

describe("stopBackgroundWatchersNotInSession", () => {
  it("drops tasks and watchers from other sessions", async () => {
    const {
      registerBackgroundTask,
      stopBackgroundWatchersNotInSession,
      useBackgroundTasksStore,
    } = await loadModule();
    const sub = makeSubscribe();
    registerBackgroundTask({
      sessionId: "s1",
      toolCallId: "tc1",
      toolName: "t",
    });
    registerBackgroundTask({
      sessionId: "s2",
      toolCallId: "tc2",
      toolName: "t",
    });
    stopBackgroundWatchersNotInSession("s1");
    const ids = useBackgroundTasksStore
      .getState()
      .tasks.map((t) => t.toolCallId);
    expect(ids).toEqual(["tc1"]);
    expect(sub.abort).toHaveBeenCalledTimes(1);
  });

  it("tears down everything for an empty session id", async () => {
    const {
      registerBackgroundTask,
      stopBackgroundWatchersNotInSession,
      useBackgroundTasksStore,
    } = await loadModule();
    makeSubscribe();
    registerBackgroundTask({
      sessionId: "s1",
      toolCallId: "tc1",
      toolName: "t",
    });
    registerBackgroundTask({
      sessionId: "s2",
      toolCallId: "tc2",
      toolName: "t",
    });
    stopBackgroundWatchersNotInSession("");
    expect(useBackgroundTasksStore.getState().tasks).toHaveLength(0);
  });
});

describe("hydrateBackgroundTasksForSession", () => {
  it("registers only still-offloaded tool calls", async () => {
    const { hydrateBackgroundTasksForSession, useBackgroundTasksStore } =
      await loadModule();
    makeSubscribe();
    mocks.list.mockResolvedValue({
      items: [
        {
          status: "offloaded",
          tool_call_id: "tc1",
          tool_name: "shell",
          session_id: "s1",
          elapsed: 12.5,
        },
        { status: "done", tool_call_id: "tc2", tool_name: "x" },
      ],
    });
    await hydrateBackgroundTasksForSession("s1");
    const ids = useBackgroundTasksStore
      .getState()
      .tasks.map((t) => t.toolCallId);
    expect(ids).toEqual(["tc1"]);
  });

  it("is a no-op for an empty session id", async () => {
    const { hydrateBackgroundTasksForSession } = await loadModule();
    await hydrateBackgroundTasksForSession("");
    expect(mocks.list).not.toHaveBeenCalled();
  });

  it("swallows list failures", async () => {
    const { hydrateBackgroundTasksForSession } = await loadModule();
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    mocks.list.mockRejectedValue(new Error("backend down"));
    await expect(
      hydrateBackgroundTasksForSession("s1"),
    ).resolves.toBeUndefined();
    errSpy.mockRestore();
  });

  it("backs off start time by the reported elapsed seconds", async () => {
    const { hydrateBackgroundTasksForSession, useBackgroundTasksStore } =
      await loadModule();
    makeSubscribe();
    mocks.list.mockResolvedValue({
      items: [
        {
          status: "offloaded",
          tool_call_id: "tc1",
          tool_name: "shell",
          session_id: "s1",
          elapsed: 10,
        },
      ],
    });
    const before = Date.now();
    await hydrateBackgroundTasksForSession("s1");
    const task = useBackgroundTasksStore
      .getState()
      .tasks.find((t) => t.toolCallId === "tc1");
    expect(task?.startTime).toBeLessThanOrEqual(before - 9_900);
  });
});
