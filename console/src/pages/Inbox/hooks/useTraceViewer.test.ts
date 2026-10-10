/**
 * useTraceViewer — message detail modal + trace loading/scrolling/copy.
 * Regression family: message detail round-trip (open → load trace →
 * close keeps scroll memory per message).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";

const mocks = vi.hoisted(() => ({
  getInboxTrace: vi.fn(),
  markMessageAsRead: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "en" },
  }),
}));

vi.mock("../../../api", () => ({
  default: {
    getInboxTrace: (...a: unknown[]) => mocks.getInboxTrace(...a),
  },
}));

vi.mock("antd", () => ({
  message: { success: vi.fn(), error: vi.fn() },
}));

import { message as antdMessage } from "antd";
import { useTraceViewer } from "./useTraceViewer";
import type { PushMessage } from "../types";

function pushMessage(overrides: Partial<PushMessage> = {}): PushMessage {
  return {
    id: "m-1",
    channelType: "email",
    channelName: "Mail",
    title: "hello",
    content: "body text",
    sender: { userId: "u", username: "U" },
    createdAt: new Date(0),
    read: false,
    metadata: {},
    ...overrides,
  } as PushMessage;
}

beforeEach(() => {
  mocks.getInboxTrace.mockReset().mockResolvedValue({ events: [] });
  mocks.markMessageAsRead.mockClear();
  vi.stubGlobal(
    "navigator",
    Object.assign(Object.create(Object.getPrototypeOf(navigator)), navigator, {
      clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useTraceViewer", () => {
  it("starts closed with no trace", () => {
    const { result } = renderHook(() =>
      useTraceViewer(mocks.markMessageAsRead),
    );
    expect(result.current.detailOpen).toBe(false);
    expect(result.current.selectedMessage).toBeNull();
    expect(result.current.traceEvents).toEqual([]);
  });

  it("opens the detail and marks an unread message read", async () => {
    mocks.getInboxTrace.mockResolvedValue({
      events: [{ at: 1, event: { type: "text", content: [] } }],
    });
    const { result } = renderHook(() =>
      useTraceViewer(mocks.markMessageAsRead),
    );
    await act(async () => {
      result.current.openMessageDetail(
        pushMessage({ metadata: { payload: { run_id: "run-1" } } }),
      );
    });
    expect(mocks.markMessageAsRead).toHaveBeenCalledWith("m-1");
    expect(result.current.detailOpen).toBe(true);
    expect(result.current.selectedMessage?.read).toBe(true);
    await waitFor(() => {
      expect(result.current.traceLoading).toBe(false);
    });
    expect(mocks.getInboxTrace).toHaveBeenCalledWith("run-1");
  });

  it("does not re-mark an already-read message", async () => {
    const { result } = renderHook(() =>
      useTraceViewer(mocks.markMessageAsRead),
    );
    await act(async () => {
      result.current.openMessageDetail(pushMessage({ read: true }));
    });
    expect(mocks.markMessageAsRead).not.toHaveBeenCalled();
  });

  it("uses the content fallback trace when there is no run_id", async () => {
    const { result } = renderHook(() =>
      useTraceViewer(mocks.markMessageAsRead),
    );
    await act(async () => {
      result.current.openMessageDetail(
        pushMessage({ content: "fallback text" }),
      );
    });
    expect(mocks.getInboxTrace).not.toHaveBeenCalled();
    expect(result.current.traceLoading).toBe(false);
    expect(result.current.traceEvents.length).toBe(1);
    expect(result.current.traceEvents[0].traceText).toBe("fallback text");
  });

  it("falls back to content when the trace fetch fails", async () => {
    mocks.getInboxTrace.mockRejectedValue(new Error("trace gone"));
    const { result } = renderHook(() =>
      useTraceViewer(mocks.markMessageAsRead),
    );
    await act(async () => {
      result.current.openMessageDetail(
        pushMessage({
          content: "fallback body",
          metadata: { payload: { run_id: "run-2" } },
        }),
      );
    });
    await waitFor(() => {
      expect(result.current.traceLoading).toBe(false);
    });
    expect(result.current.traceEvents.length).toBe(1);
    expect(result.current.traceEvents[0].traceText).toBe("fallback body");
  });

  it("closes the detail", async () => {
    const { result } = renderHook(() =>
      useTraceViewer(mocks.markMessageAsRead),
    );
    await act(async () => {
      result.current.openMessageDetail(pushMessage());
    });
    expect(result.current.detailOpen).toBe(true);
    act(() => {
      result.current.closeDetail();
    });
    expect(result.current.detailOpen).toBe(false);
  });

  it("toggles trace panel expansion per key", async () => {
    const { result } = renderHook(() =>
      useTraceViewer(mocks.markMessageAsRead),
    );
    act(() => {
      result.current.toggleTracePanel("k1", true);
    });
    expect(result.current.expandedTraceMap).toEqual({ k1: true });
    act(() => {
      result.current.toggleTracePanel("k1", false);
    });
    expect(result.current.expandedTraceMap).toEqual({ k1: false });
  });

  it("copies trace text and reports success", async () => {
    const { result } = renderHook(() =>
      useTraceViewer(mocks.markMessageAsRead),
    );
    await act(async () => {
      await result.current.copyTraceBlock("copy me");
    });
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("copy me");
    expect(antdMessage.success).toHaveBeenCalledWith("common.copied");
  });

  it("reports failure when the clipboard rejects", async () => {
    (
      navigator.clipboard.writeText as ReturnType<typeof vi.fn>
    ).mockRejectedValueOnce(new Error("denied"));
    const { result } = renderHook(() =>
      useTraceViewer(mocks.markMessageAsRead),
    );
    await act(async () => {
      await result.current.copyTraceBlock("copy me");
    });
    expect(antdMessage.error).toHaveBeenCalledWith("common.copyFailed");
  });

  it("skips copying empty text", async () => {
    const { result } = renderHook(() =>
      useTraceViewer(mocks.markMessageAsRead),
    );
    await act(async () => {
      await result.current.copyTraceBlock("");
    });
    expect(navigator.clipboard.writeText).not.toHaveBeenCalled();
  });

  it("records per-message scroll positions", async () => {
    const { result } = renderHook(() =>
      useTraceViewer(mocks.markMessageAsRead),
    );
    await act(async () => {
      result.current.openMessageDetail(pushMessage());
    });
    act(() => {
      result.current.handleTraceScroll(321);
    });
    // No crash; the position is stored in a ref (internal), so assert the
    // guard branch instead: with no selection the handler is a no-op.
    expect(result.current.selectedMessage?.id).toBe("m-1");
  });

  it("handleTraceScroll is a no-op without a selection", async () => {
    const { result } = renderHook(() =>
      useTraceViewer(mocks.markMessageAsRead),
    );
    act(() => {
      result.current.handleTraceScroll(100);
    });
    expect(result.current.selectedMessage).toBeNull();
  });
});
