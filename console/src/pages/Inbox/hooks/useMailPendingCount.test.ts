/**
 * useMailPendingCount — pending-approval sender polling and the
 * "new arrival" wobble signal. Regression family: inbox badge accuracy.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";

const mocks = vi.hoisted(() => ({
  getMailPendingAll: vi.fn(),
}));

vi.mock("../../../api/modules/mailAccessControl", () => ({
  mailAccessControlApi: {
    getMailPendingAll: (...a: unknown[]) => mocks.getMailPendingAll(...a),
  },
}));

import { useMailPendingCount } from "./useMailPendingCount";

beforeEach(() => {
  mocks.getMailPendingAll.mockReset().mockResolvedValue([]);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useMailPendingCount", () => {
  it("reports zero pending when the list is empty", async () => {
    const { result } = renderHook(() => useMailPendingCount());
    await waitFor(() => {
      expect(mocks.getMailPendingAll).toHaveBeenCalled();
    });
    expect(result.current.pendingCount).toBe(0);
    expect(result.current.newArrival).toBe(false);
  });

  it("counts pending entries and flags new arrivals", async () => {
    mocks.getMailPendingAll.mockResolvedValue([
      { agent_id: "a", sender_address: "x@y.com" },
      { agent_id: "a", sender_address: "z@y.com" },
    ]);
    const { result } = renderHook(() => useMailPendingCount());
    await waitFor(() => {
      expect(result.current.pendingCount).toBe(2);
    });
    // First sighting counts as a new arrival (nothing seen yet)
    expect(result.current.newArrival).toBe(true);
  });

  it("stops flagging arrivals after markSeen", async () => {
    mocks.getMailPendingAll.mockResolvedValue([
      { agent_id: "a", sender_address: "x@y.com" },
    ]);
    const { result } = renderHook(() => useMailPendingCount());
    await waitFor(() => {
      expect(result.current.pendingCount).toBe(1);
    });
    expect(result.current.newArrival).toBe(true);
    act(() => {
      result.current.markSeen();
    });
    expect(result.current.newArrival).toBe(false);
    // A re-poll with the same senders does not re-flag
    await act(async () => {
      await result.current.refresh();
    });
    expect(result.current.newArrival).toBe(false);
  });

  it("flags a brand-new sender seen after markSeen", async () => {
    mocks.getMailPendingAll.mockResolvedValue([
      { agent_id: "a", sender_address: "old@y.com" },
    ]);
    const { result } = renderHook(() => useMailPendingCount());
    await waitFor(() => {
      expect(result.current.pendingCount).toBe(1);
    });
    act(() => {
      result.current.markSeen();
    });
    mocks.getMailPendingAll.mockResolvedValue([
      { agent_id: "a", sender_address: "old@y.com" },
      { agent_id: "b", sender_address: "new@y.com" },
    ]);
    await act(async () => {
      await result.current.refresh();
    });
    expect(result.current.pendingCount).toBe(2);
    expect(result.current.newArrival).toBe(true);
  });

  it("keeps previous state when polling fails", async () => {
    mocks.getMailPendingAll
      .mockResolvedValueOnce([{ agent_id: "a", sender_address: "x@y.com" }])
      .mockRejectedValueOnce(new Error("network"));
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const { result } = renderHook(() => useMailPendingCount());
    await waitFor(() => {
      expect(result.current.pendingCount).toBe(1);
    });
    await act(async () => {
      await result.current.refresh();
    });
    expect(result.current.pendingCount).toBe(1);
    errSpy.mockRestore();
  });

  it("polls on the interval while visible", async () => {
    vi.useFakeTimers();
    renderHook(() => useMailPendingCount());
    await act(async () => {
      await Promise.resolve();
    });
    const before = mocks.getMailPendingAll.mock.calls.length;
    await act(async () => {
      vi.advanceTimersByTime(6000);
    });
    expect(mocks.getMailPendingAll.mock.calls.length).toBe(before + 1);
    vi.useRealTimers();
  });

  it("handles a null response as an empty list", async () => {
    mocks.getMailPendingAll.mockResolvedValue(null);
    const { result } = renderHook(() => useMailPendingCount());
    await waitFor(() => {
      expect(mocks.getMailPendingAll).toHaveBeenCalled();
    });
    expect(result.current.pendingCount).toBe(0);
  });
});
