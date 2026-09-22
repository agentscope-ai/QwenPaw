import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  getPushMessages: vi.fn(),
  setApprovals: vi.fn(),
}));

vi.mock("../../api/modules/console", () => ({
  consoleApi: {
    getPushMessages: mocks.getPushMessages,
  },
}));

vi.mock("../../contexts/ApprovalContext", () => ({
  useApprovalContext: () => ({
    approvals: [],
    setApprovals: mocks.setApprovals,
  }),
}));

import ConsolePollService from "./index";
import type { PendingApproval, PushMessage } from "../../api/modules/console";

const POLL_INTERVAL_MS = 2500;
const AUTO_DISMISS_MS = 8000;
const TITLE_BLINK_PREFIX = "\u2022 ";

const msg = (id: string, text = `text ${id}`): PushMessage => ({ id, text });

const approval = (over: Partial<PendingApproval> = {}): PendingApproval =>
  ({
    request_id: "r1",
    session_id: "s1",
    root_session_id: "s1",
    agent_id: "a1",
    tool_name: "execute_shell_command",
    severity: "info",
    findings_count: 0,
    findings_summary: "",
    tool_params: {},
    ...over,
  }) as PendingApproval;

const respond = (
  messages: PushMessage[] = [],
  pending_approvals?: PendingApproval[],
) => ({
  messages,
  ...(pending_approvals ? { pending_approvals } : {}),
});

/** Advance the poll interval and let the request settle. */
const poll = async (ms = POLL_INTERVAL_MS) => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
};

/** Set document.hidden, which jsdom exposes only as a getter. */
const setHidden = (hidden: boolean) => {
  Object.defineProperty(document, "hidden", {
    configurable: true,
    get: () => hidden,
  });
};

const fireVisibility = (state: "visible" | "hidden") => {
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => state,
  });
  act(() => {
    document.dispatchEvent(new Event("visibilitychange"));
  });
};

describe("ConsolePollService", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mocks.getPushMessages.mockReset();
    mocks.setApprovals.mockReset();
    mocks.getPushMessages.mockResolvedValue(respond([]));
    document.title = "QwenPaw";
    setHidden(false);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    setHidden(false);
  });

  // ── initial render and polling ──────────────────────────────────────────

  it("renders nothing while there are no messages", async () => {
    const { container } = render(<ConsolePollService />);
    await poll(0);

    expect(container).toBeEmptyDOMElement();
    expect(mocks.getPushMessages).toHaveBeenCalledTimes(1);
  });

  it("polls immediately on mount and then on the interval", async () => {
    render(<ConsolePollService />);
    await poll(0);
    expect(mocks.getPushMessages).toHaveBeenCalledTimes(1);

    await poll();
    expect(mocks.getPushMessages).toHaveBeenCalledTimes(2);

    await poll();
    expect(mocks.getPushMessages).toHaveBeenCalledTimes(3);
  });

  it("stops polling on unmount", async () => {
    const { unmount } = render(<ConsolePollService />);
    await poll(0);

    unmount();
    await poll(10000);

    expect(mocks.getPushMessages).toHaveBeenCalledTimes(1);
  });

  it("keeps polling after a request rejects", async () => {
    mocks.getPushMessages
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue(respond([msg("m1")]));
    render(<ConsolePollService />);

    await poll(0);
    await poll();

    expect(mocks.getPushMessages).toHaveBeenCalledTimes(2);
    expect(screen.getByText("text m1")).toBeInTheDocument();
  });

  // ── bubbles ─────────────────────────────────────────────────────────────

  it("renders a bubble per new message", async () => {
    mocks.getPushMessages.mockResolvedValue(respond([msg("m1"), msg("m2")]));
    render(<ConsolePollService />);

    await poll(0);

    expect(screen.getByText("text m1")).toBeInTheDocument();
    expect(screen.getByText("text m2")).toBeInTheDocument();
    expect(screen.getByRole("region")).toHaveAttribute(
      "aria-label",
      "Cron messages",
    );
  });

  it("does not show the same message id twice", async () => {
    mocks.getPushMessages.mockResolvedValue(respond([msg("m1")]));
    render(<ConsolePollService />);

    await poll(0);
    await poll();
    await poll();

    expect(screen.getAllByText("text m1")).toHaveLength(1);
  });

  it("shows only the two newest messages from a single poll", async () => {
    mocks.getPushMessages.mockResolvedValue(
      respond([msg("m1"), msg("m2"), msg("m3")]),
    );
    render(<ConsolePollService />);

    await poll(0);

    // MAX_NEW_PER_POLL = 2, taken from the tail of the batch.
    expect(screen.queryByText("text m1")).not.toBeInTheDocument();
    expect(screen.getByText("text m2")).toBeInTheDocument();
    expect(screen.getByText("text m3")).toBeInTheDocument();
  });

  it("keeps at most four bubbles visible across polls", async () => {
    mocks.getPushMessages.mockResolvedValue(respond([msg("m1"), msg("m2")]));
    render(<ConsolePollService />);
    await poll(0);

    mocks.getPushMessages.mockResolvedValue(respond([msg("m3"), msg("m4")]));
    await poll();

    mocks.getPushMessages.mockResolvedValue(respond([msg("m5"), msg("m6")]));
    await poll();

    // MAX_VISIBLE_BUBBLES = 4, keeping the most recent.
    const bubbles = screen.getAllByLabelText("Close");
    expect(bubbles).toHaveLength(4);
    expect(screen.queryByText("text m1")).not.toBeInTheDocument();
    expect(screen.queryByText("text m2")).not.toBeInTheDocument();
    expect(screen.getByText("text m3")).toBeInTheDocument();
    expect(screen.getByText("text m6")).toBeInTheDocument();
  });

  it("auto-dismisses a bubble once its lifetime elapses", async () => {
    mocks.getPushMessages.mockResolvedValue(respond([msg("m1")]));
    render(<ConsolePollService />);
    await poll(0);
    expect(screen.getByText("text m1")).toBeInTheDocument();

    // The sweeper runs every 500ms; just before the deadline nothing is dropped.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(AUTO_DISMISS_MS - 600);
    });
    expect(screen.getByText("text m1")).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(screen.queryByText("text m1")).not.toBeInTheDocument();
  });

  it("renders nothing again once every bubble has been dismissed", async () => {
    mocks.getPushMessages.mockResolvedValue(respond([msg("m1")]));
    const { container } = render(<ConsolePollService />);
    await poll(0);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(AUTO_DISMISS_MS + 1000);
    });

    expect(container).toBeEmptyDOMElement();
  });

  it("removes a single bubble when its close button is clicked", async () => {
    mocks.getPushMessages.mockResolvedValue(respond([msg("m1"), msg("m2")]));
    render(<ConsolePollService />);
    await poll(0);

    const first = screen.getByText("text m1").closest("div");
    // fireEvent, not userEvent: userEvent waits on real timers internally and
    // deadlocks against the fake timers this suite runs under.
    act(() => {
      fireEvent.click(first!.querySelector("button")!);
    });

    expect(screen.queryByText("text m1")).not.toBeInTheDocument();
    expect(screen.getByText("text m2")).toBeInTheDocument();
  });

  it("does not re-add a dismissed message id on the next poll", async () => {
    mocks.getPushMessages.mockResolvedValue(respond([msg("m1")]));
    render(<ConsolePollService />);
    await poll(0);

    const bubble = screen.getByText("text m1").closest("div");
    act(() => {
      fireEvent.click(bubble!.querySelector("button")!);
    });
    expect(screen.queryByText("text m1")).not.toBeInTheDocument();

    await poll();
    // The id stays in the seen set, so dismissing is not undone by the next poll.
    expect(screen.queryByText("text m1")).not.toBeInTheDocument();
  });

  it("clears the seen set once it grows past its cap", async () => {
    // 501 distinct ids across two polls: the cap is 500, so the set is cleared
    // and ids from the first batch become eligible again.
    const first = Array.from({ length: 501 }, (_, i) => msg(`f${i}`));
    mocks.getPushMessages.mockResolvedValueOnce(respond(first));
    render(<ConsolePollService />);
    await poll(0);

    mocks.getPushMessages.mockResolvedValueOnce(respond([msg("f0")]));
    await poll();

    // f0 was forgotten by the clear, so it is treated as new again; only the
    // two newest are shown, and f0 is among them.
    expect(screen.getByText("text f0")).toBeInTheDocument();
  });

  it("ignores a response with an empty message list", async () => {
    mocks.getPushMessages.mockResolvedValue(respond([]));
    const { container } = render(<ConsolePollService />);

    await poll(0);
    await poll();

    expect(container).toBeEmptyDOMElement();
  });

  it("ignores a response that carries no messages field", async () => {
    mocks.getPushMessages.mockResolvedValue({});
    const { container } = render(<ConsolePollService />);

    await poll(0);

    expect(container).toBeEmptyDOMElement();
  });

  it("ignores a null response", async () => {
    mocks.getPushMessages.mockResolvedValue(null);
    const { container } = render(<ConsolePollService />);

    await poll(0);

    expect(container).toBeEmptyDOMElement();
  });

  // ── pending approvals ───────────────────────────────────────────────────

  it("forwards pending approvals to the context", async () => {
    const approvals = [approval({ request_id: "r1" })];
    mocks.getPushMessages.mockResolvedValue(respond([], approvals));
    render(<ConsolePollService />);

    await poll(0);

    expect(mocks.setApprovals).toHaveBeenCalledTimes(1);
    expect(mocks.setApprovals).toHaveBeenCalledWith(approvals);
  });

  it("does not push approvals again while they are unchanged", async () => {
    const approvals = [approval({ request_id: "r1" })];
    mocks.getPushMessages.mockResolvedValue(respond([], approvals));
    render(<ConsolePollService />);

    await poll(0);
    await poll();
    await poll();

    // The serialised comparison exists to avoid re-rendering Chat every 2.5s.
    expect(mocks.setApprovals).toHaveBeenCalledTimes(1);
  });

  it("pushes approvals again once they change", async () => {
    mocks.getPushMessages.mockResolvedValue(
      respond([], [approval({ request_id: "r1" })]),
    );
    render(<ConsolePollService />);
    await poll(0);

    mocks.getPushMessages.mockResolvedValue(
      respond([], [approval({ request_id: "r2" })]),
    );
    await poll();

    expect(mocks.setApprovals).toHaveBeenCalledTimes(2);
    expect(mocks.setApprovals).toHaveBeenLastCalledWith([
      approval({ request_id: "r2" }),
    ]);
  });

  it("pushes approvals when the list goes from empty to non-empty", async () => {
    mocks.getPushMessages.mockResolvedValue(respond([], []));
    render(<ConsolePollService />);
    await poll(0);
    expect(mocks.setApprovals).toHaveBeenCalledTimes(1);

    mocks.getPushMessages.mockResolvedValue(
      respond([], [approval({ request_id: "r9" })]),
    );
    await poll();

    expect(mocks.setApprovals).toHaveBeenCalledTimes(2);
  });

  it("skips the approvals update when the field is absent", async () => {
    mocks.getPushMessages.mockResolvedValue({ messages: [] });
    render(<ConsolePollService />);

    await poll(0);

    expect(mocks.setApprovals).not.toHaveBeenCalled();
  });

  it("handles approvals and message bubbles in the same response", async () => {
    mocks.getPushMessages.mockResolvedValue(
      respond([msg("m1")], [approval({ request_id: "r1" })]),
    );
    render(<ConsolePollService />);

    await poll(0);

    expect(mocks.setApprovals).toHaveBeenCalledTimes(1);
    expect(screen.getByText("text m1")).toBeInTheDocument();
  });

  // ── title blinking ──────────────────────────────────────────────────────

  it("does not blink the title while the tab is visible", async () => {
    mocks.getPushMessages.mockResolvedValue(respond([msg("m1")]));
    render(<ConsolePollService />);
    await poll(0);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });

    expect(document.title).toBe("QwenPaw");
  });

  it("blinks the title while a bubble is shown and the tab is hidden", async () => {
    setHidden(true);
    mocks.getPushMessages.mockResolvedValue(respond([msg("m1")]));
    render(<ConsolePollService />);
    await poll(0);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(800);
    });
    expect(document.title).toBe(`${TITLE_BLINK_PREFIX}QwenPaw`);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(800);
    });
    expect(document.title).toBe("QwenPaw");
  });

  it("restores the title once the last bubble disappears", async () => {
    setHidden(true);
    mocks.getPushMessages.mockResolvedValue(respond([msg("m1")]));
    render(<ConsolePollService />);
    await poll(0);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(AUTO_DISMISS_MS + 1000);
    });

    expect(document.title).toBe("QwenPaw");
  });

  it("restores the title when the tab becomes visible again", async () => {
    setHidden(true);
    mocks.getPushMessages.mockResolvedValue(respond([msg("m1")]));
    render(<ConsolePollService />);
    await poll(0);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(800);
    });
    expect(document.title).toBe(`${TITLE_BLINK_PREFIX}QwenPaw`);

    setHidden(false);
    fireVisibility("visible");

    expect(document.title).toBe("QwenPaw");
  });

  it("ignores a visibilitychange to hidden", async () => {
    setHidden(true);
    mocks.getPushMessages.mockResolvedValue(respond([msg("m1")]));
    render(<ConsolePollService />);
    await poll(0);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(800);
    });
    const blinking = document.title;

    fireVisibility("hidden");

    // Only the "visible" branch restores the title.
    expect(document.title).toBe(blinking);
  });

  it("does not start a second blink loop when more bubbles arrive", async () => {
    setHidden(true);
    mocks.getPushMessages.mockResolvedValue(respond([msg("m1")]));
    render(<ConsolePollService />);
    await poll(0);

    mocks.getPushMessages.mockResolvedValue(respond([msg("m2")]));
    await poll();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(800);
    });

    // A doubled loop would flip the prefix twice and land back on the plain title.
    expect(document.title).toBe(`${TITLE_BLINK_PREFIX}QwenPaw`);
  });

  it("restores the title on unmount while blinking", async () => {
    setHidden(true);
    mocks.getPushMessages.mockResolvedValue(respond([msg("m1")]));
    const { unmount } = render(<ConsolePollService />);
    await poll(0);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(800);
    });
    expect(document.title).toBe(`${TITLE_BLINK_PREFIX}QwenPaw`);

    unmount();

    expect(document.title).toBe("QwenPaw");
  });

  it("captures the title that was present at mount", async () => {
    document.title = "Original Page";
    setHidden(true);
    mocks.getPushMessages.mockResolvedValue(respond([msg("m1")]));
    render(<ConsolePollService />);
    await poll(0);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(800);
    });

    expect(document.title).toBe(`${TITLE_BLINK_PREFIX}Original Page`);
  });
});
