// @vitest-environment jsdom
/**
 * BackgroundTaskPanel tests — session-scoped background task queue UI:
 * empty-state render, collapse toggle, badge counts, finished-task filter,
 * per-task cancel/remove, batch cancel-all / clear-finished, expandable
 * output pane, status text formatting and embedded mode.
 */
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

const storeState = vi.hoisted(() => ({
  tasks: [] as Record<string, unknown>[],
  removeTask: vi.fn(),
  removeTasks: vi.fn(),
}));
const mockCancel = vi.hoisted(() => vi.fn());
const mockStopWatcher = vi.hoisted(() => vi.fn());
const mockMessage = vi.hoisted(() => ({
  info: vi.fn(),
  error: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) => {
      if (typeof fallback === "string") return fallback;
      if (fallback && typeof fallback === "object") {
        const obj = fallback as Record<string, unknown>;
        if (typeof obj.defaultValue === "string") {
          return typeof obj.count === "number"
            ? obj.defaultValue.replace("{{count}}", String(obj.count))
            : obj.defaultValue;
        }
      }
      return key;
    },
  }),
}));

vi.mock("../../../contexts/ThemeContext", () => ({
  useTheme: () => ({ isDark: false }),
}));

vi.mock("../../../stores/backgroundTasksStore", () => ({
  useBackgroundTasksStore: (selector: (s: typeof storeState) => unknown) =>
    selector(storeState),
  selectTasksForSession: (
    tasks: Record<string, unknown>[],
    sessionId: string,
  ) => (sessionId ? tasks.filter((t) => t.sessionId === sessionId) : []),
}));

vi.mock("../../../hooks/useBackgroundTaskWatcher", () => ({
  cancelBackgroundTask: (sessionId: string, toolCallId: string) =>
    mockCancel(sessionId, toolCallId),
  stopBackgroundTaskWatcher: (toolCallId: string) =>
    mockStopWatcher(toolCallId),
}));

vi.mock("antd", () => ({
  message: mockMessage,
}));

import BackgroundTaskPanel from "./BackgroundTaskPanel";

const baseTask = (over: Record<string, unknown>) => ({
  toolCallId: "tc-1",
  sessionId: "sess-1",
  toolName: "run_tool_batch",
  status: "running",
  startTime: Date.now() - 5000,
  endTime: null,
  liveOutput: "live...",
  result: "",
  ...over,
});

beforeEach(() => {
  storeState.tasks = [];
  storeState.removeTask.mockClear();
  storeState.removeTasks.mockClear();
  mockCancel.mockReset();
  mockStopWatcher.mockClear();
  mockMessage.info.mockClear();
  mockMessage.error.mockClear();
});

describe("BackgroundTaskPanel basics", () => {
  it("renders nothing when the session has no tasks", () => {
    const { container } = render(<BackgroundTaskPanel sessionId="sess-1" />);
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing for an empty session id even with tasks present", () => {
    storeState.tasks = [baseTask({})];
    const { container } = render(<BackgroundTaskPanel sessionId="" />);
    expect(container.firstChild).toBeNull();
  });

  it("shows the title, running badge count and collapses the list by default", () => {
    storeState.tasks = [
      baseTask({ toolCallId: "a" }),
      baseTask({ toolCallId: "b" }),
      baseTask({ toolCallId: "c", status: "done", endTime: Date.now() }),
    ];
    render(<BackgroundTaskPanel sessionId="sess-1" />);
    expect(screen.getByText("Background tasks")).toBeTruthy();
    expect(screen.getByText("2")).toBeTruthy(); // badge: running count only
    // collapsed by default: task rows hidden
    expect(screen.queryByText("run_tool_batch")).toBeNull();
  });

  it("expanding the panel shows rows and a cancel button per running task", () => {
    storeState.tasks = [baseTask({})];
    render(<BackgroundTaskPanel sessionId="sess-1" />);
    fireEvent.click(screen.getByText("Background tasks"));
    expect(screen.getAllByText("run_tool_batch").length).toBeGreaterThan(0);
    expect(screen.getByText(/Running/)).toBeTruthy();
    expect(screen.getByText("Cancel")).toBeTruthy();
  });

  it("shows the hidden-finished hint when nothing is running but finished tasks exist", () => {
    storeState.tasks = [
      baseTask({ status: "done", endTime: Date.now() }),
      baseTask({ toolCallId: "x", status: "cancelled", endTime: Date.now() }),
    ];
    render(<BackgroundTaskPanel sessionId="sess-1" />);
    fireEvent.click(screen.getByText("Background tasks"));
    expect(screen.getByText("2 completed (hidden)")).toBeTruthy();
  });

  it("shows the finished task when the toggle is on instead of the empty hint", () => {
    storeState.tasks = [baseTask({ status: "done", endTime: Date.now() })];
    render(<BackgroundTaskPanel sessionId="sess-1" />);
    fireEvent.click(screen.getByText("Background tasks"));
    expect(screen.queryByText("No running tasks")).toBeNull();
    fireEvent.click(screen.getByLabelText("Show completed"));
    expect(screen.getAllByText("run_tool_batch").length).toBeGreaterThan(0);
  });
});

describe("BackgroundTaskPanel finished filter and statuses", () => {
  it("formats done and cancelled status texts with durations", () => {
    const start = Date.now() - 125000; // 2m 5s
    storeState.tasks = [
      baseTask({
        toolCallId: "d",
        status: "done",
        startTime: start,
        endTime: start + 125000,
      }),
      baseTask({
        toolCallId: "c",
        status: "cancelled",
        startTime: start,
        endTime: start + 5000,
      }),
    ];
    render(<BackgroundTaskPanel sessionId="sess-1" />);
    fireEvent.click(screen.getByText("Background tasks"));
    fireEvent.click(screen.getByLabelText("Show completed"));
    expect(screen.getByText(/Task completed · Total 2m 5s/)).toBeTruthy();
    expect(screen.getByText(/Cancelled · Total 5s/)).toBeTruthy();
  });

  it("removes finished tasks and stops their watchers on close", () => {
    storeState.tasks = [
      baseTask({ toolCallId: "done-1", status: "done", endTime: Date.now() }),
    ];
    render(<BackgroundTaskPanel sessionId="sess-1" />);
    fireEvent.click(screen.getByText("Background tasks"));
    fireEvent.click(screen.getByLabelText("Show completed"));
    fireEvent.click(screen.getByText("Remove"));
    expect(mockStopWatcher).toHaveBeenCalledWith("done-1");
    expect(storeState.removeTask).toHaveBeenCalledWith("done-1");
  });

  it("cancels a running task on close", async () => {
    mockCancel.mockResolvedValue(undefined);
    storeState.tasks = [baseTask({ toolCallId: "run-1" })];
    render(<BackgroundTaskPanel sessionId="sess-1" />);
    fireEvent.click(screen.getByText("Background tasks"));
    fireEvent.click(screen.getByText("Cancel"));
    await vi.waitFor(() => expect(mockMessage.info).toHaveBeenCalled());
    expect(mockCancel).toHaveBeenCalledWith("sess-1", "run-1");
  });

  it("reports a toast when cancelling fails", async () => {
    mockCancel.mockRejectedValue(new Error("nope"));
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    storeState.tasks = [baseTask({ toolCallId: "run-2" })];
    render(<BackgroundTaskPanel sessionId="sess-1" />);
    fireEvent.click(screen.getByText("Background tasks"));
    fireEvent.click(screen.getByText("Cancel"));
    await vi.waitFor(() => expect(mockMessage.error).toHaveBeenCalled());
    consoleSpy.mockRestore();
  });
});

describe("BackgroundTaskPanel batch actions", () => {
  it("cancels all running tasks and reports completion", async () => {
    mockCancel.mockResolvedValue(undefined);
    storeState.tasks = [
      baseTask({ toolCallId: "r1" }),
      baseTask({ toolCallId: "r2" }),
      baseTask({ toolCallId: "f1", status: "done", endTime: Date.now() }),
    ];
    render(<BackgroundTaskPanel sessionId="sess-1" />);
    fireEvent.click(screen.getByText("Background tasks"));
    fireEvent.click(screen.getByText("Cancel all"));
    await vi.waitFor(() => expect(mockMessage.info).toHaveBeenCalled());
    expect(mockCancel).toHaveBeenCalledTimes(2);
  });

  it("clears finished tasks in one click", () => {
    storeState.tasks = [
      baseTask({ toolCallId: "f1", status: "done", endTime: Date.now() }),
      baseTask({ toolCallId: "f2", status: "cancelled", endTime: Date.now() }),
    ];
    render(<BackgroundTaskPanel sessionId="sess-1" />);
    fireEvent.click(screen.getByText("Background tasks"));
    fireEvent.click(screen.getByText("Clear completed"));
    expect(mockStopWatcher).toHaveBeenCalledWith("f1");
    expect(mockStopWatcher).toHaveBeenCalledWith("f2");
    expect(storeState.removeTasks).toHaveBeenCalledWith(["f1", "f2"]);
    expect(mockMessage.info).toHaveBeenCalled();
  });

  it("disables batch buttons when there is nothing to act on", () => {
    storeState.tasks = [
      baseTask({ toolCallId: "f1", status: "done", endTime: Date.now() }),
    ];
    render(<BackgroundTaskPanel sessionId="sess-1" />);
    fireEvent.click(screen.getByText("Background tasks"));
    expect(screen.getByText("Cancel all")).toBeDisabled();
    expect(screen.getByText("Clear completed")).not.toBeDisabled();
  });
});

describe("BackgroundTaskPanel output pane and embedded mode", () => {
  it("expanding a running task shows live output; collapsing hides it", () => {
    storeState.tasks = [baseTask({ liveOutput: "live progress" })];
    render(<BackgroundTaskPanel sessionId="sess-1" />);
    fireEvent.click(screen.getByText("Background tasks"));
    const row = screen.getByText("run_tool_batch").closest("[role=button]")!;
    fireEvent.click(row);
    expect(screen.getByText("live progress")).toBeTruthy();
    fireEvent.click(row);
    expect(screen.queryByText("live progress")).toBeNull();
  });

  it("shows the result for finished tasks and the fallback when empty", () => {
    storeState.tasks = [
      baseTask({
        toolCallId: "d1",
        status: "done",
        endTime: Date.now(),
        result: "final result",
      }),
      baseTask({
        toolCallId: "d2",
        status: "done",
        endTime: Date.now(),
        result: "",
        liveOutput: "",
      }),
    ];
    render(<BackgroundTaskPanel sessionId="sess-1" />);
    fireEvent.click(screen.getByText("Background tasks"));
    fireEvent.click(screen.getByLabelText("Show completed"));

    const rows = screen.getAllByText("run_tool_batch");
    fireEvent.click(rows[0].closest("[role=button]")!);
    expect(screen.getByText("final result")).toBeTruthy();

    fireEvent.click(rows[1].closest("[role=button]")!);
    expect(screen.getByText("No output yet")).toBeTruthy();
  });

  it("clears the expanded selection when the expanded task disappears", () => {
    storeState.tasks = [baseTask({ toolCallId: "gone", liveOutput: "temp" })];
    const { rerender } = render(<BackgroundTaskPanel sessionId="sess-1" />);
    fireEvent.click(screen.getByText("Background tasks"));
    fireEvent.click(
      screen.getByText("run_tool_batch").closest("[role=button]")!,
    );
    expect(screen.getByText("temp")).toBeTruthy();

    storeState.tasks = [baseTask({ toolCallId: "other" })];
    rerender(<BackgroundTaskPanel sessionId="sess-1" />);
    expect(screen.queryByText("temp")).toBeNull();
  });

  it("embedded mode skips the outer chrome and shows the body directly", () => {
    storeState.tasks = [baseTask({})];
    render(<BackgroundTaskPanel sessionId="sess-1" embedded />);
    expect(screen.queryByText("Background tasks")).toBeNull();
    expect(screen.getAllByText("run_tool_batch").length).toBeGreaterThan(0);
  });

  it("embedded mode respects the parent-controlled showFinished prop", () => {
    storeState.tasks = [
      baseTask({ toolCallId: "f1", status: "done", endTime: Date.now() }),
    ];
    render(
      <BackgroundTaskPanel sessionId="sess-1" embedded showFinished={false} />,
    );
    expect(screen.getByText("1 completed (hidden)")).toBeTruthy();
  });
});
