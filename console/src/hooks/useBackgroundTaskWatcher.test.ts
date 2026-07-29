import { beforeEach, describe, expect, it, vi } from "vitest";

const cancelApi = vi.fn();
const getOutputApi = vi.fn();
const messageError = vi.fn();
const messageSuccess = vi.fn();

vi.mock("../api/modules/toolCalls", () => ({
  toolCallsApi: {
    cancel: (...args: unknown[]) => cancelApi(...args),
    getOutput: (...args: unknown[]) => getOutputApi(...args),
  },
  subscribeToolCallStream: () => () => {},
  extractOutputText: (output: { content?: Array<{ text?: string }> }) =>
    output.content?.[0]?.text || "",
}));

vi.mock("antd", () => ({
  message: {
    error: (...args: unknown[]) => messageError(...args),
    info: vi.fn(),
    success: (...args: unknown[]) => messageSuccess(...args),
  },
}));

vi.mock("../i18n", () => ({
  default: { t: (_k: string, fallback: string) => fallback },
}));

vi.mock("../utils/resolveBackendSessionId", () => ({
  resolveBackendSessionId: (preferred?: string | null) => preferred || "",
}));

import { useBackgroundTasksStore } from "../stores/backgroundTasksStore";
import {
  cancelBackgroundTask,
  registerBackgroundTask,
  stopBackgroundWatchersNotInSession,
} from "./useBackgroundTaskWatcher";

describe("useBackgroundTaskWatcher session isolation", () => {
  beforeEach(() => {
    cancelApi.mockReset();
    getOutputApi.mockReset();
    messageError.mockReset();
    messageSuccess.mockReset();
    useBackgroundTasksStore.setState({ tasks: [] });
  });

  it("removes empty-session tasks when switching to another session", () => {
    const store = useBackgroundTasksStore.getState();
    store.addTask({
      toolCallId: "tc-a",
      toolName: "a",
      sessionId: "sid-a",
      startTime: 1,
    });
    store.addTask({
      toolCallId: "tc-empty",
      toolName: "e",
      sessionId: "",
      startTime: 2,
    });
    store.addTask({
      toolCallId: "tc-b",
      toolName: "b",
      sessionId: "sid-b",
      startTime: 3,
    });

    stopBackgroundWatchersNotInSession("sid-b");

    const left = useBackgroundTasksStore
      .getState()
      .tasks.map((t) => t.toolCallId)
      .sort();
    expect(left).toEqual(["tc-b"]);
  });

  it("refuses cancel when sessionId is empty", async () => {
    await expect(cancelBackgroundTask("", "tc-1")).rejects.toThrow(
      /Missing backend session id/,
    );
    expect(cancelApi).not.toHaveBeenCalled();
    expect(messageError).toHaveBeenCalled();
  });

  it("hydrates /output immediately when alreadyCompleted", async () => {
    getOutputApi.mockResolvedValue({
      tool_call_id: "tc-fast",
      is_closed: true,
      final_state: "success",
      content: [{ text: "fast-done" }],
    });

    registerBackgroundTask({
      sessionId: "sid-fast",
      toolCallId: "tc-fast",
      toolName: "shell",
      alreadyCompleted: true,
    });

    await vi.waitFor(() => {
      const task = useBackgroundTasksStore
        .getState()
        .tasks.find((t) => t.toolCallId === "tc-fast");
      expect(task?.status).toBe("done");
      expect(task?.result).toBe("fast-done");
    });
    expect(getOutputApi).toHaveBeenCalledWith("sid-fast", "tc-fast");
  });
});
