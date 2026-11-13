// @vitest-environment jsdom
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import type { ComponentProps } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const h = vi.hoisted(() => ({
  // Mirrors i18next closely enough for assertions: a string second arg is the
  // fallback, an options object may carry a defaultValue with {{placeholders}}.
  t: (key: string, opts?: unknown) => {
    if (typeof opts === "string") return opts;
    if (opts && typeof opts === "object") {
      const o = opts as Record<string, unknown>;
      if (typeof o.defaultValue === "string") {
        return o.defaultValue.replace(/\{\{(\w+)\}\}/g, (_m, k: string) =>
          String(o[k] ?? ""),
        );
      }
    }
    return key;
  },
  message: { info: vi.fn(), success: vi.fn(), error: vi.fn() },
  getInfo: vi.fn(),
  offload: vi.fn(),
  cancel: vi.fn(),
  preventOffload: vi.fn(),
  extendOffload: vi.fn(),
  extendKill: vi.fn(),
  registerBackgroundTask: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: h.t }),
}));

vi.mock("antd", () => ({ message: h.message }));

vi.mock("lucide-react", () => ({
  Clock3: () => <span data-testid="ico-clock" />,
  Hourglass: () => <span data-testid="ico-hourglass" />,
  Moon: () => <span data-testid="ico-moon" />,
  RefreshCw: () => <span data-testid="ico-refresh" />,
  X: () => <span data-testid="ico-x" />,
}));

vi.mock("../../../../api/modules/toolCalls", () => ({
  toolCallsApi: {
    getInfo: h.getInfo,
    offload: h.offload,
    cancel: h.cancel,
    preventOffload: h.preventOffload,
    extendOffload: h.extendOffload,
    extendKill: h.extendKill,
  },
}));

vi.mock("../../../../hooks/useBackgroundTaskWatcher", () => ({
  registerBackgroundTask: h.registerBackgroundTask,
}));

import { OffloadBanner } from "./ToolCallControlPopover";

const EXTEND = { offload_remaining: 40, kill_remaining: 90 };

function setup(overrides: Partial<ComponentProps<typeof OffloadBanner>> = {}) {
  const props = {
    sessionId: "s1",
    toolCallId: "tc1",
    toolName: "shell",
    offloadRemaining: 30,
    killRemaining: 60,
    totalSeconds: 60,
    defaultPolicy: "offload" as const,
    onClose: vi.fn(),
    onUpdateRemaining: vi.fn(),
    ...overrides,
  };
  const view = render(<OffloadBanner {...props} />);
  return { ...view, props };
}

function byLabel(label: string): HTMLElement {
  return screen.getByRole("button", { name: label });
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers();
  h.getInfo.mockResolvedValue({ status: "offloaded", offload_reason: "auto" });
  h.offload.mockResolvedValue(undefined);
  h.cancel.mockResolvedValue(undefined);
  h.preventOffload.mockResolvedValue(EXTEND);
  h.extendOffload.mockResolvedValue(EXTEND);
  h.extendKill.mockResolvedValue(EXTEND);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("OffloadBanner mode selection", () => {
  it("shows the armed auto-offload UI when policy is offload with a countdown", () => {
    setup();
    expect(
      screen.getByText("Tool running longer — about to offload"),
    ).toBeInTheDocument();
    expect(byLabel("Move to background now")).toBeInTheDocument();
    expect(byLabel("Don't auto-offload")).toBeInTheDocument();
    expect(byLabel("Delay offload")).toBeInTheDocument();
  });

  it("switches to the prevented UI when the offload policy has no countdown", () => {
    setup({ offloadRemaining: null });
    expect(screen.getByText("Auto-offload disabled")).toBeInTheDocument();
    expect(screen.queryByText("Don't auto-offload")).not.toBeInTheDocument();
  });

  it("shows the foreground UI for a keep_foreground policy", () => {
    setup({ defaultPolicy: "keep_foreground", offloadRemaining: null });
    expect(
      screen.getByText("Tool still running in foreground"),
    ).toBeInTheDocument();
    expect(byLabel("Move to background")).toBeInTheDocument();
  });

  it("renders the footer note only when there is no countdown", () => {
    const { unmount } = setup();
    expect(
      screen.queryByText(/Stays in foreground by default/),
    ).not.toBeInTheDocument();
    unmount();
    setup({ defaultPolicy: "keep_foreground", offloadRemaining: null });
    expect(
      screen.getByText(
        "Stays in foreground by default; you can offload anytime",
      ),
    ).toBeInTheDocument();
  });

  it("shows the offload-policy footer note when prevented", () => {
    setup({ offloadRemaining: null });
    expect(
      screen.getByText(
        "Won't auto-offload; you can move to background or cancel",
      ),
    ).toBeInTheDocument();
  });
});

describe("OffloadBanner countdown ring", () => {
  it("renders the initial seconds in the ring", () => {
    setup({ offloadRemaining: 4 });
    expect(screen.getByText("4")).toBeInTheDocument();
    expect(screen.getByLabelText("4s until auto-offload")).toBeInTheDocument();
  });

  // The urgency styling is a css-module class, so it is asserted by substring:
  // vitest's generateScopedName is "[name]__[local]__[hash]" and the probe run
  // showed the rendered value is "_urgent_bd0e12". Without these two cases the
  // `displaySecs <= 5` threshold is unobservable - mutation testing confirmed
  // that widening it to `<= 0` was NOT caught until they existed.
  it("marks the timer urgent at or below five seconds", () => {
    setup({ offloadRemaining: 5 });
    const cluster = screen.getByLabelText("5s until auto-offload");
    expect(cluster.className).toContain("urgent");
    expect(
      cluster.querySelector("div[class*='timerCount']")?.className,
    ).toContain("urgent");
  });

  it("does not mark the timer urgent above five seconds", () => {
    setup({ offloadRemaining: 6 });
    const cluster = screen.getByLabelText("6s until auto-offload");
    expect(cluster.className).not.toContain("urgent");
  });

  it("flips to urgent as the countdown crosses the threshold", () => {
    setup({ offloadRemaining: 7 });
    expect(
      screen.getByLabelText("7s until auto-offload").className,
    ).not.toContain("urgent");
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(screen.getByLabelText("5s until auto-offload").className).toContain(
      "urgent",
    );
  });

  it("ticks the display down on each second", () => {
    setup({ offloadRemaining: 30 });
    expect(screen.getByText("30")).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(screen.getByText("27")).toBeInTheDocument();
  });

  it("rounds a fractional remaining value up", () => {
    setup({ offloadRemaining: 12.2 });
    expect(screen.getByText("13")).toBeInTheDocument();
  });

  it("does not render a ring when there is no countdown", () => {
    setup({ offloadRemaining: null });
    expect(
      screen.queryByLabelText(/until auto-offload/),
    ).not.toBeInTheDocument();
  });

  it("uses the keep-mode aria copy for a foreground countdown", () => {
    setup({ defaultPolicy: "keep_foreground", offloadRemaining: 20 });
    expect(screen.getByLabelText("Panel closes in 20s")).toBeInTheDocument();
  });
});

describe("OffloadBanner auto-dismiss", () => {
  it("confirms with the backend before registering an auto-offload at zero", async () => {
    const { props } = setup({ offloadRemaining: 1 });
    await act(async () => {
      vi.advanceTimersByTime(1500);
    });
    expect(h.getInfo).toHaveBeenCalledWith("s1", "tc1");
    await act(async () => {
      await Promise.resolve();
    });
    expect(h.registerBackgroundTask).toHaveBeenCalledWith({
      sessionId: "s1",
      toolCallId: "tc1",
      toolName: "shell",
    });
    expect(h.message.info).toHaveBeenCalledWith(
      "Moved to background automatically",
    );
    // The collapse animation delays onClose by 250ms.
    act(() => {
      vi.advanceTimersByTime(250);
    });
    expect(props.onClose).toHaveBeenCalled();
  });

  it("registers an already-completed offload without the info toast", async () => {
    h.getInfo.mockResolvedValue({
      status: "completed",
      offload_reason: "auto",
    });
    setup({ offloadRemaining: 1 });
    await act(async () => {
      vi.advanceTimersByTime(1500);
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(h.registerBackgroundTask).toHaveBeenCalledWith(
      expect.objectContaining({ alreadyCompleted: true }),
    );
    expect(h.message.info).not.toHaveBeenCalled();
  });

  it("does not register when a completed call has no offload reason", async () => {
    h.getInfo.mockResolvedValue({ status: "completed", offload_reason: null });
    setup({ offloadRemaining: 1 });
    await act(async () => {
      vi.advanceTimersByTime(1500);
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(h.registerBackgroundTask).not.toHaveBeenCalled();
  });

  it("swallows a backend failure while confirming the offload", async () => {
    h.getInfo.mockRejectedValue(new Error("boom"));
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    setup({ offloadRemaining: 1 });
    await act(async () => {
      vi.advanceTimersByTime(1500);
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(h.registerBackgroundTask).not.toHaveBeenCalled();
    errorSpy.mockRestore();
  });

  it("falls back to the tool call id when the tool name is empty", async () => {
    setup({ offloadRemaining: 1, toolName: "" });
    await act(async () => {
      vi.advanceTimersByTime(1500);
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(h.registerBackgroundTask).toHaveBeenCalledWith(
      expect.objectContaining({ toolName: "tc1" }),
    );
  });

  it("toasts the keep-mode dismiss without consulting the backend", async () => {
    const { props } = setup({
      defaultPolicy: "keep_foreground",
      offloadRemaining: 1,
    });
    await act(async () => {
      vi.advanceTimersByTime(1500);
    });
    expect(h.getInfo).not.toHaveBeenCalled();
    expect(h.message.info).toHaveBeenCalledWith(
      "Reminder closed; tool keeps running in foreground",
    );
    act(() => {
      vi.advanceTimersByTime(250);
    });
    expect(props.onClose).toHaveBeenCalled();
  });

  it("auto-dismisses a foreground panel when the server clears the deadline", async () => {
    const { props, rerender } = setup({
      defaultPolicy: "keep_foreground",
      offloadRemaining: 20,
    });
    await act(async () => {
      rerender(
        <OffloadBanner
          sessionId="s1"
          toolCallId="tc1"
          toolName="shell"
          offloadRemaining={null}
          killRemaining={60}
          totalSeconds={60}
          defaultPolicy="keep_foreground"
          onClose={props.onClose}
          onUpdateRemaining={props.onUpdateRemaining}
        />,
      );
    });
    expect(h.message.info).toHaveBeenCalledWith(
      "Reminder closed; tool keeps running in foreground",
    );
    act(() => {
      vi.advanceTimersByTime(250);
    });
    expect(props.onClose).toHaveBeenCalled();
  });

  it("keeps an offload-policy panel open when the deadline is cleared", () => {
    const { props, rerender } = setup({ offloadRemaining: 20 });
    rerender(
      <OffloadBanner
        sessionId="s1"
        toolCallId="tc1"
        toolName="shell"
        offloadRemaining={null}
        killRemaining={60}
        totalSeconds={60}
        defaultPolicy="offload"
        onClose={props.onClose}
        onUpdateRemaining={props.onUpdateRemaining}
      />,
    );
    // The prevented UI replaces the armed one but the panel stays mounted.
    expect(screen.getByText("Auto-offload disabled")).toBeInTheDocument();
    expect(props.onClose).not.toHaveBeenCalled();
  });

  it("does not re-arm the timer for a zero remaining value", () => {
    setup({ offloadRemaining: 0 });
    expect(
      screen.queryByLabelText(/until auto-offload/),
    ).not.toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(h.getInfo).not.toHaveBeenCalled();
  });
});

describe("OffloadBanner actions", () => {
  it("moves the tool to the background and dismisses", async () => {
    setup();
    await act(async () => {
      fireEvent.click(byLabel("Move to background now"));
    });
    expect(h.offload).toHaveBeenCalledWith("s1", "tc1");
    expect(h.registerBackgroundTask).toHaveBeenCalledWith({
      sessionId: "s1",
      toolCallId: "tc1",
      toolName: "shell",
    });
    expect(h.message.success).toHaveBeenCalledWith("Tool moved to background");
    act(() => {
      vi.advanceTimersByTime(250);
    });
  });

  it("prevents the auto-offload and reports the new remaining values", async () => {
    const { props } = setup();
    await act(async () => {
      fireEvent.click(byLabel("Don't auto-offload"));
    });
    expect(h.preventOffload).toHaveBeenCalledWith("s1", "tc1");
    expect(props.onUpdateRemaining).toHaveBeenCalledWith(40, 90);
    expect(h.message.info).toHaveBeenCalledWith("Continuing to wait…");
  });

  it("delays the offload by thirty seconds", async () => {
    const { props } = setup();
    await act(async () => {
      fireEvent.click(byLabel("Delay offload"));
    });
    expect(h.extendOffload).toHaveBeenCalledWith("s1", "tc1", 30);
    expect(props.onUpdateRemaining).toHaveBeenCalledWith(40, 90);
    expect(h.message.info).toHaveBeenCalledWith(
      "Offload delayed; will remind you in +30s",
    );
  });

  it("extends the kill timeout by the constant", async () => {
    const { props } = setup();
    await act(async () => {
      fireEvent.click(byLabel("Extend timeout"));
    });
    expect(h.extendKill).toHaveBeenCalledWith("s1", "tc1", 30);
    expect(props.onUpdateRemaining).toHaveBeenCalledWith(40, 90);
    expect(h.message.info).toHaveBeenCalledWith("Timeout extended by 30s");
  });

  it("cancels the tool call and dismisses", async () => {
    setup();
    await act(async () => {
      fireEvent.click(byLabel("tool.control.cancel"));
    });
    expect(h.cancel).toHaveBeenCalledWith("s1", "tc1");
    expect(h.message.info).toHaveBeenCalledWith("Tool call cancelled");
  });

  // NOTE: this pins the observable contract (buttons disabled while busy, so a
  // second click cannot start another action). The `if (busy) return` guard
  // inside withGuard is NOT separately observable through the UI: fireEvent on a
  // disabled button never reaches the handler, so removing that line is an
  // equivalent mutant here. It is defence-in-depth for programmatic invocation.
  it("ignores a second click while an action is in flight", async () => {
    let release!: () => void;
    h.offload.mockReturnValue(
      new Promise<void>((resolve) => {
        release = resolve;
      }),
    );
    setup();
    await act(async () => {
      fireEvent.click(byLabel("Move to background now"));
    });
    // Every button is disabled while busy.
    expect(byLabel("Don't auto-offload")).toBeDisabled();
    await act(async () => {
      fireEvent.click(byLabel("Don't auto-offload"));
    });
    expect(h.preventOffload).not.toHaveBeenCalled();
    await act(async () => {
      release();
    });
    expect(h.offload).toHaveBeenCalledTimes(1);
  });
});

describe("OffloadBanner error mapping", () => {
  const cases: Array<[string, string]> = [
    [
      "a 404 from the backend",
      "Tool call not found (it may have already finished).",
    ],
    [
      "tool call not found here",
      "Tool call not found (it may have already finished).",
    ],
    [
      "HTTP 409 conflict",
      "Action rejected (tool state changed or limit reached).",
    ],
    [
      "cannot offload right now",
      "Action rejected (tool state changed or limit reached).",
    ],
    [
      "cannot cancel this call",
      "Action rejected (tool state changed or limit reached).",
    ],
    [
      "cannot extend any further",
      "Action rejected (tool state changed or limit reached).",
    ],
    ["Failed to fetch", "Network error. Check your connection and try again."],
    [
      "NetworkError when attempting",
      "Network error. Check your connection and try again.",
    ],
    [
      "network request failed",
      "Network error. Check your connection and try again.",
    ],
    [
      "something else entirely",
      "Action failed. The tool may have finished or the request was rejected.",
    ],
  ];

  it.each(cases)("maps %s to the right toast", async (_label, expected) => {
    h.cancel.mockRejectedValue(new Error(_label));
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    setup();
    await act(async () => {
      fireEvent.click(byLabel("tool.control.cancel"));
    });
    expect(h.message.error).toHaveBeenCalledWith(expected);
    errorSpy.mockRestore();
  });

  it("stringifies a non-Error rejection before mapping it", async () => {
    h.cancel.mockRejectedValue("plain string failure");
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    setup();
    await act(async () => {
      fireEvent.click(byLabel("tool.control.cancel"));
    });
    expect(h.message.error).toHaveBeenCalledWith(
      "Action failed. The tool may have finished or the request was rejected.",
    );
    errorSpy.mockRestore();
  });

  it("treats a null rejection as an empty message", async () => {
    h.cancel.mockRejectedValue(null);
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    setup();
    await act(async () => {
      fireEvent.click(byLabel("tool.control.cancel"));
    });
    expect(h.message.error).toHaveBeenCalledWith(
      "Action failed. The tool may have finished or the request was rejected.",
    );
    errorSpy.mockRestore();
  });
});

describe("OffloadBanner extend-kill cap", () => {
  it("disables Extend timeout when adding 30s would pass the hard cap", () => {
    // elapsed 40 + kill 60 + 30 = 130 > cap 100
    setup({ maxInternalTimeoutSecs: 100, elapsed: 40, killRemaining: 60 });
    const btn = byLabel("Extend timeout");
    expect(btn).toBeDisabled();
    expect(btn).toHaveAttribute(
      "title",
      "Action rejected (tool state changed or limit reached).",
    );
  });

  it("enables Extend timeout when the extension still fits the cap", () => {
    // elapsed 0 + kill 60 + 30 = 90 <= cap 100
    setup({ maxInternalTimeoutSecs: 100, elapsed: 0, killRemaining: 60 });
    const btn = byLabel("Extend timeout");
    expect(btn).not.toBeDisabled();
    expect(btn).not.toHaveAttribute("title");
  });

  it("accepts an extension that lands exactly on the cap", () => {
    // elapsed 10 + kill 60 + 30 = 100 <= cap 100 + 0.01
    setup({ maxInternalTimeoutSecs: 100, elapsed: 10, killRemaining: 60 });
    expect(byLabel("Extend timeout")).not.toBeDisabled();
  });

  it("never caps when maxInternalTimeoutSecs is null", () => {
    setup({ maxInternalTimeoutSecs: null, elapsed: 9999, killRemaining: 9999 });
    expect(byLabel("Extend timeout")).not.toBeDisabled();
  });

  it("treats a missing kill remaining as zero when checking the cap", () => {
    // elapsed 60 + 0 + 30 = 90 <= 100
    setup({ maxInternalTimeoutSecs: 100, elapsed: 60, killRemaining: null });
    expect(byLabel("Extend timeout")).not.toBeDisabled();
  });
});

describe("OffloadBanner timer cleanup", () => {
  it("clears the interval when unmounted mid-countdown", () => {
    const clearSpy = vi.spyOn(global, "clearInterval");
    const { unmount } = setup({ offloadRemaining: 30 });
    unmount();
    expect(clearSpy).toHaveBeenCalled();
    clearSpy.mockRestore();
  });
});
