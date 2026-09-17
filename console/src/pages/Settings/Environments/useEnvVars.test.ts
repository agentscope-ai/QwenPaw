import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";

const hoisted = vi.hoisted(() => ({
  apiMocks: { listEnvs: vi.fn() },
}));

vi.mock("../../../api", () => ({
  __esModule: true,
  default: hoisted.apiMocks,
}));

import { useEnvVars } from "./useEnvVars";

const { apiMocks } = hoisted;

describe("useEnvVars", () => {
  beforeEach(() => {
    apiMocks.listEnvs.mockReset();
  });

  it("loads env vars on mount and sets loading false on success", async () => {
    const data = [{ key: "API_KEY", value: "v" }];
    apiMocks.listEnvs.mockResolvedValue(data);

    const { result } = renderHook(() => useEnvVars());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });
    expect(result.current.envVars).toEqual(data);
    expect(result.current.error).toBeNull();
  });

  it("sets error from thrown Error message on failure", async () => {
    apiMocks.listEnvs.mockRejectedValue(new Error("network down"));

    const { result } = renderHook(() => useEnvVars());

    await waitFor(() => {
      expect(result.current.error).toBe("network down");
    });
    expect(result.current.loading).toBe(false);
  });

  it("uses fallback message when rejection is not an Error", async () => {
    apiMocks.listEnvs.mockRejectedValue("boom");

    const { result } = renderHook(() => useEnvVars());

    await waitFor(() => {
      expect(result.current.error).toBe("Failed to load environment variables");
    });
  });

  it("fetchAll can be retried after error", async () => {
    apiMocks.listEnvs.mockRejectedValueOnce(new Error("once"));
    apiMocks.listEnvs.mockResolvedValue([{ key: "K", value: "1" }]);

    const { result } = renderHook(() => useEnvVars());

    await waitFor(() => {
      expect(result.current.error).toBe("once");
    });

    await act(async () => {
      await result.current.fetchAll();
    });

    await waitFor(() => {
      expect(result.current.envVars).toEqual([{ key: "K", value: "1" }]);
    });
    expect(result.current.error).toBeNull();
  });
});
