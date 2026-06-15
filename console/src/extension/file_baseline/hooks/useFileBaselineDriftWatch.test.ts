import { describe, it, expect, vi, afterEach } from "vitest";
import { renderHook } from "@testing-library/react";
import { useFileBaselineDriftWatch } from "./useFileBaselineDriftWatch";

vi.mock("@/api/config", () => ({
  getApiUrl: (path: string) => `/api${path}`,
}));

vi.mock("@/api/authHeaders", () => ({
  buildAuthHeaders: vi.fn(() => ({ Authorization: "Bearer test" })),
}));

describe("useFileBaselineDriftWatch", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("does not connect when disabled (PB-S51 gate)", async () => {
    global.fetch = vi.fn();
    const { unmount } = renderHook(() => useFileBaselineDriftWatch(vi.fn(), false));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(fetch).not.toHaveBeenCalled();
    unmount();
  });
});

/**
 * SSE payload parsing and reconnect behavior are covered by backend PB-S50/S51
 * integration tests. The hook uses a process-wide reconnect loop that is unsafe
 * to exercise in unit tests without aborting the worker; keep enabled-path checks
 * in component tests via mocked useFileBaselineDriftWatch.
 */
