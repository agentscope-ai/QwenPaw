// @vitest-environment jsdom
/**
 * ChatSenderTabsPanel tests — the two-tab strip the composer renders above the
 * input when a session has background tasks and/or queued messages.
 *
 * Covered behaviour (all of it is the container's own contract, the two child
 * panels are probed rather than rendered): suppression when the session has
 * nothing to show, which tab is picked on mount, the badge count rules, the
 * "show completed" filter hand-off, cancel-all / clear-completed batch actions
 * with their guards and their all-settled semantics, the paused / error run
 * states in the queue toolbar, tab switching, the fallback that moves the
 * active tab when its list empties, and verbatim prop forwarding to both
 * children.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const h = vi.hoisted(() => ({
  isDark: false,
  bgTasks: [] as Record<string, unknown>[],
  queueItems: [] as Record<string, unknown>[],
  runState: "idle",
  removeTasks: vi.fn(),
  cancelBackgroundTask: vi.fn(),
  stopBackgroundTaskWatcher: vi.fn(),
  message: {
    info: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
    success: vi.fn(),
  },
  bgPanelProps: [] as Record<string, unknown>[],
  queuePanelProps: [] as Record<string, unknown>[],
}));

// Keys are called with an inline fallback ("Cancel all") and without one
// ("chat.queue.pause"), so the fallback-less form resolves against the real
// English locale: an assertion on the visible label then also pins the key.
vi.mock("react-i18next", async () => {
  const en = (await import("../../../locales/en.json")).default as Record<
    string,
    unknown
  >;
  const dig = (obj: Record<string, unknown>, path: string): unknown =>
    path
      .split(".")
      .reduce<unknown>(
        (cur, seg) =>
          cur && typeof cur === "object"
            ? (cur as Record<string, unknown>)[seg]
            : undefined,
        obj,
      );
  return {
    useTranslation: () => ({
      t: (key: string, fallback?: unknown) => {
        if (typeof fallback === "string") return fallback;
        const v = dig(en, key);
        return typeof v === "string" ? v : key;
      },
      i18n: { language: "en" },
    }),
  };
});

vi.mock("../../../contexts/ThemeContext", () => ({
  useTheme: () => ({ isDark: h.isDark }),
}));

vi.mock("../../../stores/backgroundTasksStore", () => ({
  useBackgroundTasksStore: (selector: (s: unknown) => unknown) =>
    selector({ tasks: h.bgTasks, removeTasks: h.removeTasks }),
  // The component scopes the store to one session; keep that scoping real so a
  // cross-session leak would fail these tests instead of being hidden.
  selectTasksForSession: (
    tasks: Record<string, unknown>[],
    sessionId: string,
  ) => (sessionId ? tasks.filter((t) => t.sessionId === sessionId) : []),
}));

vi.mock("../../../stores/messageQueueStore", () => ({
  useMessageQueueStore: (selector: (s: unknown) => unknown) =>
    selector({
      queues: { "sess-q": h.queueItems },
      runStates: { "sess-q": h.runState },
    }),
}));

vi.mock("../../../hooks/useBackgroundTaskWatcher", () => ({
  cancelBackgroundTask: (sessionId: string, toolCallId: string) =>
    h.cancelBackgroundTask(sessionId, toolCallId),
  stopBackgroundTaskWatcher: (toolCallId: string) =>
    h.stopBackgroundTaskWatcher(toolCallId),
}));

// The shared icons stub (src/test/icons-mock.ts) does not export every name this
// component imports, and the stub is shared by the whole repo, so missing names
// are supplied here instead of editing it. Spreading importActual keeps every
// stub icon that does exist (same shape: a <span data-icon=name>).
vi.mock("@agentscope-ai/icons", async () => {
  const icons = await vi.importActual<Record<string, unknown>>(
    "@agentscope-ai/icons",
  );
  const stub = (name: string) => (props: Record<string, unknown>) => (
    <span data-icon={name} {...props} />
  );
  return {
    ...icons,
    SparkStopCircleLine: stub("SparkStopCircleLine"),
  };
});

vi.mock("antd", () => ({
  message: h.message,
  // The panel only uses Tooltip to wrap its own buttons; render the child so
  // the buttons stay reachable by role/label.
  Tooltip: ({ children }: { children?: unknown }) => children ?? null,
}));

vi.mock("./BackgroundTaskPanel", async () => {
  const React = await import("react");
  return {
    default: (props: Record<string, unknown>) => {
      h.bgPanelProps.push(props);
      return React.createElement("div", {
        "data-testid": "bg-panel",
        "data-session-id": String(props.sessionId),
        "data-embedded": String(props.embedded),
        "data-show-finished": String(props.showFinished),
      });
    },
  };
});

vi.mock("./MessageQueuePanel", async () => {
  const React = await import("react");
  return {
    default: (props: Record<string, unknown>) => {
      h.queuePanelProps.push(props);
      return React.createElement("div", {
        "data-testid": "queue-panel",
        "data-run-state": String(props.runState),
        "data-item-count": String((props.items as unknown[]).length),
        "data-embedded": String(props.embedded),
      });
    },
  };
});

import ChatSenderTabsPanel from "./ChatSenderTabsPanel";

const BG_SESSION = "sess-bg";
const QUEUE_SESSION = "sess-q";

function task(over: Record<string, unknown> = {}) {
  return {
    toolCallId: "tc-1",
    toolName: "run_tool_batch",
    sessionId: BG_SESSION,
    startTime: 1_700_000_000_000,
    endTime: null,
    status: "running",
    liveOutput: "",
    result: null,
    hintVisible: false,
    ...over,
  };
}

function queueItem(over: Record<string, unknown> = {}) {
  return {
    id: "q1",
    text: "first queued message",
    status: "pending",
    retryCount: 0,
    createdAt: 1_700_000_000_000,
    ...over,
  };
}

/** One fresh set of callbacks per render so forwarding can be asserted by identity. */
function callbacks() {
  return {
    onRemove: vi.fn(),
    onEdit: vi.fn(),
    onReorder: vi.fn(),
    onInterruptAndSend: vi.fn(),
    onClear: vi.fn(),
    onPauseResume: vi.fn(),
    onRetry: vi.fn(),
    onSkip: vi.fn(),
  };
}

function renderPanel(extra: Record<string, unknown> = {}) {
  const props = callbacks();
  const utils = render(
    <ChatSenderTabsPanel
      bgSessionId={BG_SESSION}
      queueSessionId={QUEUE_SESSION}
      {...props}
      {...extra}
    />,
  );
  return { ...utils, props };
}

function bgTab() {
  return screen.getByRole("button", { name: /Background tasks/ });
}

function queueTab() {
  return screen.getByRole("button", { name: /Message queue/ });
}

beforeEach(() => {
  h.isDark = false;
  h.bgTasks = [];
  h.queueItems = [];
  h.runState = "idle";
  h.bgPanelProps = [];
  h.queuePanelProps = [];
  h.removeTasks.mockReset();
  h.cancelBackgroundTask.mockReset();
  h.stopBackgroundTaskWatcher.mockReset();
  h.message.info.mockReset();
  h.message.error.mockReset();
  h.message.warning.mockReset();
  h.message.success.mockReset();
});

describe("ChatSenderTabsPanel visibility", () => {
  it("falls back to an empty queue and the idle run state when the session has no store entry", () => {
    // Both stores are read through a `?? ` fallback: a session that never
    // enqueued anything has no key at all, and the panel must not crash nor
    // invent a queue tab for it.
    h.bgTasks = [task()];
    const { container } = render(
      <ChatSenderTabsPanel
        bgSessionId={BG_SESSION}
        queueSessionId="sess-never-enqueued"
        {...callbacks()}
      />,
    );
    expect(container.firstChild).not.toBeNull();
    expect(screen.getByTestId("bg-panel")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Message queue/ })).toBeNull();
  });

  it("renders nothing when the session has no background task and no queued message", () => {
    const { container } = renderPanel();
    expect(container.firstChild).toBeNull();
  });

  it("shows only the queue tab when there is a queue but no background task", () => {
    h.queueItems = [queueItem()];
    renderPanel();
    expect(queueTab()).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: /Background tasks/ }),
    ).toBeNull();
    expect(screen.getByTestId("queue-panel")).toBeTruthy();
    expect(screen.queryByTestId("bg-panel")).toBeNull();
  });

  it("shows only the background tab when there are tasks but no queue", () => {
    h.bgTasks = [task()];
    renderPanel();
    expect(bgTab()).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Message queue/ })).toBeNull();
    expect(screen.getByTestId("bg-panel")).toBeTruthy();
    expect(screen.queryByTestId("queue-panel")).toBeNull();
  });

  it("scopes each store to its own session id", () => {
    h.bgTasks = [task()];
    h.queueItems = [queueItem()];
    renderPanel();
    // The bg panel must get the background session, never the queue session.
    expect(screen.getByTestId("bg-panel").dataset.sessionId).toBe(BG_SESSION);
    expect(screen.getByTestId("bg-panel").dataset.sessionId).not.toBe(
      QUEUE_SESSION,
    );
  });

  it("ignores background tasks that belong to another session", () => {
    h.bgTasks = [task({ toolCallId: "other", sessionId: "sess-other" })];
    const { container } = renderPanel();
    expect(container.firstChild).toBeNull();
  });
});

describe("ChatSenderTabsPanel initial tab", () => {
  it("opens on the background tab while a task is still running", () => {
    h.bgTasks = [task()];
    h.queueItems = [queueItem()];
    renderPanel();
    expect(screen.getByTestId("bg-panel")).toBeTruthy();
    expect(screen.queryByTestId("queue-panel")).toBeNull();
  });

  it("opens on the queue tab when nothing runs but a queue exists", () => {
    h.bgTasks = [task({ status: "done", endTime: 1_700_000_001_000 })];
    h.queueItems = [queueItem()];
    renderPanel();
    expect(screen.getByTestId("queue-panel")).toBeTruthy();
    expect(screen.queryByTestId("bg-panel")).toBeNull();
  });

  it("opens on the background tab when only finished tasks exist and there is no queue", () => {
    h.bgTasks = [task({ status: "cancelled", endTime: 1_700_000_001_000 })];
    renderPanel();
    expect(screen.getByTestId("bg-panel")).toBeTruthy();
  });
});

describe("ChatSenderTabsPanel background badge", () => {
  it("counts only the running tasks in the badge", () => {
    h.bgTasks = [
      task({ toolCallId: "a" }),
      task({ toolCallId: "b" }),
      task({ toolCallId: "c", status: "done", endTime: 1_700_000_001_000 }),
    ];
    renderPanel();
    expect(screen.getByText("2")).toBeTruthy();
    expect(screen.queryByText("3")).toBeNull();
  });

  it("hides the badge while finished tasks stay collapsed", () => {
    h.bgTasks = [task({ status: "done", endTime: 1_700_000_001_000 })];
    renderPanel();
    // One finished task, collapsed: no count is rendered at all.
    expect(screen.queryByText("1")).toBeNull();
  });

  it("turns the badge into the finished count once 'show completed' is on", () => {
    h.bgTasks = [
      task({ status: "done", endTime: 1_700_000_001_000 }),
      task({
        toolCallId: "b",
        status: "cancelled",
        endTime: 1_700_000_002_000,
      }),
    ];
    renderPanel();
    expect(screen.queryByText("2")).toBeNull();
    fireEvent.click(screen.getByRole("checkbox"));
    expect(screen.getByText("2")).toBeTruthy();
  });
});

describe("ChatSenderTabsPanel show-completed hand-off", () => {
  it("starts collapsed and forwards the filter to the embedded panel", () => {
    h.bgTasks = [task()];
    renderPanel();
    const checkbox = screen.getByRole("checkbox") as HTMLInputElement;
    expect(checkbox.checked).toBe(false);
    expect(screen.getByTestId("bg-panel").dataset.showFinished).toBe("false");
    expect(screen.getByTestId("bg-panel").dataset.embedded).toBe("true");
  });

  it("forwards the toggled filter to the embedded panel", () => {
    h.bgTasks = [task()];
    renderPanel();
    fireEvent.click(screen.getByRole("checkbox"));
    expect((screen.getByRole("checkbox") as HTMLInputElement).checked).toBe(
      true,
    );
    expect(screen.getByTestId("bg-panel").dataset.showFinished).toBe("true");
  });
});

describe("ChatSenderTabsPanel cancel-all", () => {
  it("is disabled while nothing is running", () => {
    h.bgTasks = [task({ status: "done", endTime: 1_700_000_001_000 })];
    renderPanel();
    const btn = screen.getByRole("button", { name: /Cancel all/ });
    expect(btn.hasAttribute("disabled")).toBe(true);
  });

  it("is enabled as soon as one task runs", () => {
    h.bgTasks = [task()];
    renderPanel();
    const btn = screen.getByRole("button", { name: /Cancel all/ });
    expect(btn.hasAttribute("disabled")).toBe(false);
  });

  it("does not touch the watcher when the guarded click happens with nothing running", async () => {
    h.bgTasks = [task({ status: "done", endTime: 1_700_000_001_000 })];
    renderPanel();
    // The button is disabled, but the guard must hold even if a click lands.
    fireEvent.click(screen.getByRole("button", { name: /Cancel all/ }));
    await waitFor(() => expect(h.message.info).not.toHaveBeenCalled());
    expect(h.cancelBackgroundTask).not.toHaveBeenCalled();
  });

  it("cancels every running task of this session and reports the batch as done", async () => {
    h.bgTasks = [
      task({ toolCallId: "a" }),
      task({ toolCallId: "b" }),
      task({ toolCallId: "c", status: "done", endTime: 1_700_000_001_000 }),
    ];
    h.cancelBackgroundTask.mockResolvedValue(undefined);
    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: /Cancel all/ }));
    await waitFor(() => expect(h.message.info).toHaveBeenCalledTimes(1));
    expect(h.message.info.mock.calls[0][0]).toBe("Cancelled all running tasks");
    // Finished tasks must not be re-cancelled.
    expect(h.cancelBackgroundTask).toHaveBeenCalledTimes(2);
    expect(h.cancelBackgroundTask).toHaveBeenCalledWith(BG_SESSION, "a");
    expect(h.cancelBackgroundTask).toHaveBeenCalledWith(BG_SESSION, "b");
  });

  it("still reports the batch as done when one cancellation rejects", async () => {
    h.bgTasks = [task({ toolCallId: "a" }), task({ toolCallId: "b" })];
    h.cancelBackgroundTask
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce(undefined);
    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: /Cancel all/ }));
    await waitFor(() => expect(h.message.info).toHaveBeenCalledTimes(1));
    expect(h.cancelBackgroundTask).toHaveBeenCalledTimes(2);
  });

  it("re-enables the batch buttons after the cancellations settle", async () => {
    h.bgTasks = [task({ toolCallId: "a" })];
    h.cancelBackgroundTask.mockResolvedValue(undefined);
    renderPanel();
    const btn = screen.getByRole("button", { name: /Cancel all/ });
    fireEvent.click(btn);
    await waitFor(() => expect(h.message.info).toHaveBeenCalledTimes(1));
    // batchBusy is cleared in the finally block, so the button is usable again.
    await waitFor(() =>
      expect(
        screen
          .getByRole("button", { name: /Cancel all/ })
          .hasAttribute("disabled"),
      ).toBe(false),
    );
  });
});

describe("ChatSenderTabsPanel clear-completed", () => {
  it("is disabled while nothing has finished", () => {
    h.bgTasks = [task()];
    renderPanel();
    expect(
      screen
        .getByRole("button", { name: /Clear completed/ })
        .hasAttribute("disabled"),
    ).toBe(true);
  });

  it("stops the watcher of each finished task, removes them and reports", () => {
    h.bgTasks = [
      task({ toolCallId: "a" }),
      task({ toolCallId: "b", status: "done", endTime: 1_700_000_001_000 }),
      task({
        toolCallId: "c",
        status: "cancelled",
        endTime: 1_700_000_002_000,
      }),
    ];
    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: /Clear completed/ }));
    expect(h.stopBackgroundTaskWatcher).toHaveBeenCalledTimes(2);
    expect(h.stopBackgroundTaskWatcher).toHaveBeenCalledWith("b");
    expect(h.stopBackgroundTaskWatcher).toHaveBeenCalledWith("c");
    expect(h.stopBackgroundTaskWatcher).not.toHaveBeenCalledWith("a");
    expect(h.removeTasks).toHaveBeenCalledTimes(1);
    expect(h.removeTasks).toHaveBeenCalledWith(["b", "c"]);
    expect(h.message.info.mock.calls[0][0]).toBe("Cleared completed tasks");
  });

  it("does not fire when the guarded click happens with nothing finished", () => {
    h.bgTasks = [task()];
    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: /Clear completed/ }));
    expect(h.stopBackgroundTaskWatcher).not.toHaveBeenCalled();
    expect(h.removeTasks).not.toHaveBeenCalled();
    expect(h.message.info).not.toHaveBeenCalled();
  });
});

describe("ChatSenderTabsPanel queue toolbar", () => {
  it("shows the pause action while the queue runs", () => {
    h.queueItems = [queueItem()];
    h.runState = "running";
    renderPanel();
    expect(screen.getByRole("button", { name: /Pause queue/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Resume queue/ })).toBeNull();
    expect(screen.queryByText("Paused")).toBeNull();
    expect(screen.queryByText("Send failed")).toBeNull();
  });

  it("shows the paused hint and switches the action to resume", () => {
    h.queueItems = [queueItem()];
    h.runState = "paused";
    renderPanel();
    expect(screen.getByText("Paused")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Resume queue/ })).toBeTruthy();
    expect(screen.queryByText("Send failed")).toBeNull();
  });

  it("shows the send-failed hint and switches the action to resume", () => {
    h.queueItems = [queueItem()];
    h.runState = "error";
    renderPanel();
    expect(screen.getByText("Send failed")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Resume queue/ })).toBeTruthy();
    expect(screen.queryByText("Paused")).toBeNull();
  });

  it("calls the pause/resume handler from the toolbar action", () => {
    h.queueItems = [queueItem()];
    const { props } = renderPanel();
    fireEvent.click(screen.getByRole("button", { name: /Pause queue/ }));
    expect(props.onPauseResume).toHaveBeenCalledTimes(1);
  });

  it("hides the clear action while a single message is queued", () => {
    h.queueItems = [queueItem()];
    renderPanel();
    expect(screen.queryByRole("button", { name: /Clear queue/ })).toBeNull();
  });

  it("offers the clear action once more than one message is queued", () => {
    h.queueItems = [queueItem(), queueItem({ id: "q2", text: "second" })];
    const { props } = renderPanel();
    const clear = screen.getByRole("button", { name: /Clear queue/ });
    fireEvent.click(clear);
    expect(props.onClear).toHaveBeenCalledTimes(1);
  });
});

describe("ChatSenderTabsPanel tab switching and fallback", () => {
  it("switches to the queue tab on click", () => {
    h.bgTasks = [task()];
    h.queueItems = [queueItem()];
    renderPanel();
    expect(screen.getByTestId("bg-panel")).toBeTruthy();
    fireEvent.click(queueTab());
    expect(screen.getByTestId("queue-panel")).toBeTruthy();
    expect(screen.queryByTestId("bg-panel")).toBeNull();
  });

  it("switches back to the background tab on click", () => {
    h.bgTasks = [task()];
    h.queueItems = [queueItem()];
    renderPanel();
    fireEvent.click(queueTab());
    fireEvent.click(bgTab());
    expect(screen.getByTestId("bg-panel")).toBeTruthy();
    expect(screen.queryByTestId("queue-panel")).toBeNull();
  });

  it("falls back to the queue tab when the background list empties", () => {
    h.bgTasks = [task()];
    h.queueItems = [queueItem()];
    const { rerender, props } = renderPanel();
    expect(screen.getByTestId("bg-panel")).toBeTruthy();

    h.bgTasks = [];
    rerender(
      <ChatSenderTabsPanel
        bgSessionId={BG_SESSION}
        queueSessionId={QUEUE_SESSION}
        {...props}
      />,
    );
    expect(screen.getByTestId("queue-panel")).toBeTruthy();
    expect(screen.queryByTestId("bg-panel")).toBeNull();
  });

  it("falls back to the background tab when the queue empties", () => {
    h.bgTasks = [task()];
    h.queueItems = [queueItem()];
    const { rerender, props } = renderPanel();
    // Start on the queue tab, then drop the queue while a task still runs.
    fireEvent.click(queueTab());
    expect(screen.getByTestId("queue-panel")).toBeTruthy();

    h.queueItems = [];
    rerender(
      <ChatSenderTabsPanel
        bgSessionId={BG_SESSION}
        queueSessionId={QUEUE_SESSION}
        {...props}
      />,
    );
    expect(screen.getByTestId("bg-panel")).toBeTruthy();
    expect(screen.queryByTestId("queue-panel")).toBeNull();
  });

  it("renders nothing once both lists are gone", () => {
    h.bgTasks = [task()];
    const { rerender, props, container } = renderPanel();
    expect(screen.getByTestId("bg-panel")).toBeTruthy();

    h.bgTasks = [];
    rerender(
      <ChatSenderTabsPanel
        bgSessionId={BG_SESSION}
        queueSessionId={QUEUE_SESSION}
        {...props}
      />,
    );
    expect(container.firstChild).toBeNull();
  });
});

describe("ChatSenderTabsPanel prop forwarding", () => {
  it("forwards the queue payload verbatim to the embedded queue panel", () => {
    const items = [queueItem(), queueItem({ id: "q2", text: "second" })];
    h.queueItems = items;
    h.runState = "paused";
    renderPanel();
    const panel = screen.getByTestId("queue-panel");
    expect(panel.dataset.runState).toBe("paused");
    expect(panel.dataset.itemCount).toBe("2");
    expect(panel.dataset.embedded).toBe("true");
    const last = h.queuePanelProps[h.queuePanelProps.length - 1];
    expect(last.items).toBe(items);
  });

  it("forwards all eight queue callbacks by identity", () => {
    h.queueItems = [queueItem()];
    const { props } = renderPanel();
    const last = h.queuePanelProps[h.queuePanelProps.length - 1];
    for (const name of [
      "onRemove",
      "onEdit",
      "onReorder",
      "onInterruptAndSend",
      "onClear",
      "onPauseResume",
      "onRetry",
      "onSkip",
    ]) {
      expect(last[name]).toBe(props[name as keyof typeof props]);
    }
  });

  it("uses the dark finished-only badge palette", () => {
    // Fourth arm of the nested badge-colour ternary: no running task + dark.
    h.isDark = true;
    h.bgTasks = [task({ status: "done", endTime: 1_700_000_001_000 })];
    renderPanel();
    fireEvent.click(screen.getByRole("checkbox"));
    expect(screen.getByText("1")).toBeTruthy();
  });

  it("renders the dark palette variant without changing the structure", () => {
    h.isDark = true;
    h.bgTasks = [task()];
    h.queueItems = [queueItem()];
    renderPanel();
    expect(screen.getByTestId("bg-panel")).toBeTruthy();
    expect(bgTab()).toBeTruthy();
    expect(queueTab()).toBeTruthy();
  });
});
