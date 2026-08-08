import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const getInfo = vi.fn();
const getOffloadPolicy = vi.fn();
let resolvePreferred: (preferred?: string | null) => string = () =>
  "backend-sid";

vi.mock("../api/modules/toolCalls", () => ({
  toolCallsApi: {
    getInfo: (...args: unknown[]) => getInfo(...args),
    getOffloadPolicy: (...args: unknown[]) => getOffloadPolicy(...args),
  },
}));

vi.mock("../utils/resolveBackendSessionId", () => ({
  resolveBackendSessionId: (preferred?: string | null) =>
    resolvePreferred(preferred),
}));

const registerBackgroundTask = vi.fn();

vi.mock("./useBackgroundTaskWatcher", () => ({
  registerBackgroundTask: (...args: unknown[]) =>
    registerBackgroundTask(...args),
}));

vi.mock("../stores/backgroundTasksStore", () => ({
  useBackgroundTasksStore: {
    getState: () => ({ tasks: [] }),
  },
}));

import { useToolCallControl } from "./useToolCallControl";

describe("useToolCallControl", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    getInfo.mockReset();
    getOffloadPolicy.mockReset();
    registerBackgroundTask.mockReset();
    getOffloadPolicy.mockResolvedValue({ default_action: "keep_foreground" });
    resolvePreferred = (preferred?: string | null) =>
      preferred || "backend-sid";
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("keeps killRemaining ticking after offload countdown hits zero", async () => {
    let nowMs = 0;
    vi.spyOn(performance, "now").mockImplementation(() => nowMs);

    getInfo.mockImplementation(async () => ({
      status: "running",
      offload_remaining: nowMs >= 1000 ? 0 : 1,
      kill_remaining: Math.max(0, 5 - nowMs / 1000),
    }));

    const { result } = renderHook(() =>
      useToolCallControl("backend-sid", "tc-1", true, "shell"),
    );

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(result.current.defaultPolicy).toBe("keep_foreground");
    expect(result.current.offloadRemaining).toBe(1);
    expect(result.current.killRemaining).toBe(5);

    await act(async () => {
      nowMs += 1000;
      vi.advanceTimersByTime(1000);
    });

    // Offload window closed; kill countdown must keep ticking locally.
    expect(result.current.offloadRemaining).toBe(0);
    expect(result.current.killRemaining).not.toBeNull();
    expect(result.current.killRemaining as number).toBeLessThanOrEqual(4);

    const killAfterOffloadZero = result.current.killRemaining as number;

    await act(async () => {
      nowMs += 1000;
      vi.advanceTimersByTime(1000);
      await Promise.resolve();
    });

    expect(result.current.killRemaining as number).toBeLessThan(
      killAfterOffloadZero,
    );
  });

  it("loads offload policy from settings", async () => {
    getOffloadPolicy.mockResolvedValue({ default_action: "offload" });
    getInfo.mockResolvedValue({
      status: "running",
      offload_remaining: 20,
      kill_remaining: null,
    });

    const { result } = renderHook(() =>
      useToolCallControl("backend-sid", "tc-2", true),
    );

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(result.current.defaultPolicy).toBe("offload");
  });

  it("retries getInfo after session id becomes available", async () => {
    let mappedSid = "";
    resolvePreferred = () => mappedSid;

    getInfo.mockImplementation(async (sid: string) => {
      if (sid !== "backend-ready") return null;
      return {
        status: "running",
        offload_remaining: 12,
        kill_remaining: 40,
      };
    });

    const { result } = renderHook(() =>
      useToolCallControl("", "tc-retry", true, "shell"),
    );

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(result.current.offloadRemaining).toBeNull();
    expect(getInfo).not.toHaveBeenCalled();

    mappedSid = "backend-ready";

    await act(async () => {
      vi.advanceTimersByTime(250);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(getInfo).toHaveBeenCalledWith("backend-ready", "tc-retry");
    expect(result.current.offloadRemaining).toBe(12);
    expect(result.current.killRemaining).toBe(40);
  });

  it("does not register foreground completions into the bg task panel", async () => {
    getInfo.mockResolvedValue({
      status: "completed",
      offload_remaining: null,
      kill_remaining: null,
      offload_reason: null,
    });

    const { rerender } = renderHook(
      ({ calling }: { calling: boolean }) =>
        useToolCallControl("backend-sid", "tc-fg", calling, "shell"),
      { initialProps: { calling: true } },
    );

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    await act(async () => {
      rerender({ calling: false });
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(registerBackgroundTask).not.toHaveBeenCalled();
  });

  it("does not auto-open the control panel before min foreground runtime", async () => {
    let nowMs = 0;
    vi.spyOn(performance, "now").mockImplementation(() => nowMs);

    getInfo.mockResolvedValue({
      status: "running",
      offload_remaining: 30,
      kill_remaining: 60,
      elapsed: 0,
    });

    const { result } = renderHook(() =>
      useToolCallControl("backend-sid", "tc-popup", true, "shell"),
    );

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    // First second: offload already ≤ 30, but elapsed < 15 → stay closed.
    await act(async () => {
      nowMs += 1000;
      vi.advanceTimersByTime(1000);
    });
    expect(result.current.bannerVisible).toBe(false);

    // After minWait (min(15, 30*0.5)=15s) the panel may auto-open.
    await act(async () => {
      nowMs += 14000;
      vi.advanceTimersByTime(14000);
    });
    expect(result.current.bannerVisible).toBe(true);
  });

  it("registers alreadyCompleted only when offload_reason is set", async () => {
    getInfo.mockResolvedValue({
      status: "completed",
      offload_remaining: null,
      kill_remaining: null,
      offload_reason: "timeout",
    });

    const { rerender } = renderHook(
      ({ calling }: { calling: boolean }) =>
        useToolCallControl("backend-sid", "tc-bg-fast", calling, "shell"),
      { initialProps: { calling: true } },
    );

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    await act(async () => {
      rerender({ calling: false });
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(registerBackgroundTask).toHaveBeenCalledWith(
      expect.objectContaining({
        toolCallId: "tc-bg-fast",
        alreadyCompleted: true,
      }),
    );
  });
});
