import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";

const hoisted = vi.hoisted(() => ({
  apiMocks: {
    listProviders: vi.fn(),
    getActiveModels: vi.fn(),
  },
}));

vi.mock("../../../api", () => ({
  __esModule: true,
  default: hoisted.apiMocks,
}));

vi.mock("../../../stores/agentStore", () => ({
  useAgentStore: () => ({ selectedAgent: "agent-1" }),
}));

import { useProviders } from "./useProviders";

const { apiMocks } = hoisted;

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

describe("useProviders", () => {
  beforeEach(() => {
    apiMocks.listProviders.mockReset();
    apiMocks.getActiveModels.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("loads providers and active models on mount", async () => {
    const providers = [{ provider: "openai" }];
    const active = { models: [] };
    apiMocks.listProviders.mockResolvedValue(providers);
    apiMocks.getActiveModels.mockResolvedValue(active);

    const { result } = renderHook(() => useProviders());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });
    expect(result.current.providers).toEqual(providers);
    expect(result.current.activeModels).toEqual(active);
    expect(apiMocks.getActiveModels).toHaveBeenCalledWith({ scope: "global" });
  });

  it("sets error with 'Unexpected API response' when listProviders returns non-array", async () => {
    apiMocks.listProviders.mockResolvedValue({ not: "array" });
    apiMocks.getActiveModels.mockResolvedValue({});

    const { result } = renderHook(() => useProviders());

    await waitFor(() => {
      expect(result.current.error).toContain("Unexpected API response");
    });
    expect(result.current.loading).toBe(false);
  });

  it("sets error message on fetch failure", async () => {
    apiMocks.listProviders.mockRejectedValue(new Error("fetch failed"));
    apiMocks.getActiveModels.mockResolvedValue({});

    const { result } = renderHook(() => useProviders());

    await waitFor(() => {
      expect(result.current.error).toBe("fetch failed");
    });
  });

  it("uses fallback message when rejection is not an Error", async () => {
    apiMocks.listProviders.mockRejectedValue("oops");
    apiMocks.getActiveModels.mockResolvedValue({});

    const { result } = renderHook(() => useProviders());

    await waitFor(() => {
      expect(result.current.error).toBe("Failed to load provider data");
    });
  });

  it("polls only providers while discovery is running", async () => {
    vi.useFakeTimers();
    const syncing = [{ id: "custom", models_syncing: true }];
    const settled = [{ id: "custom", models_syncing: false }];
    apiMocks.listProviders
      .mockResolvedValueOnce(syncing)
      .mockResolvedValueOnce(settled);
    apiMocks.getActiveModels.mockResolvedValue({ models: [] });

    const { result } = renderHook(() => useProviders());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.providers).toEqual(syncing);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    expect(result.current.providers).toEqual(settled);
    expect(apiMocks.listProviders).toHaveBeenCalledTimes(2);
    expect(apiMocks.getActiveModels).toHaveBeenCalledOnce();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(apiMocks.listProviders).toHaveBeenCalledTimes(2);
  });

  it("does not overlap a pending provider poll", async () => {
    vi.useFakeTimers();
    const syncing = [{ id: "custom", models_syncing: true }];
    const poll = deferred<unknown[]>();
    apiMocks.listProviders
      .mockResolvedValueOnce(syncing)
      .mockReturnValueOnce(poll.promise);
    apiMocks.getActiveModels.mockResolvedValue({ models: [] });

    renderHook(() => useProviders());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(apiMocks.listProviders).toHaveBeenCalledTimes(2);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(apiMocks.listProviders).toHaveBeenCalledTimes(2);

    await act(async () => {
      poll.resolve([{ id: "custom", models_syncing: false }]);
      await poll.promise;
    });
  });

  it("does not let a full load overwrite a newer provider poll", async () => {
    vi.useFakeTimers();
    const syncing = [{ id: "custom", models_syncing: true }];
    const settled = [{ id: "custom", models_syncing: false }];
    const staleRefresh = deferred<unknown[]>();
    apiMocks.listProviders
      .mockResolvedValueOnce(syncing)
      .mockReturnValueOnce(staleRefresh.promise)
      .mockResolvedValueOnce(settled);
    apiMocks.getActiveModels.mockResolvedValue({ models: [] });

    const { result } = renderHook(() => useProviders());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    let refresh!: Promise<void>;
    act(() => {
      refresh = result.current.fetchAll(false);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(result.current.providers).toEqual(settled);

    await act(async () => {
      staleRefresh.resolve(syncing);
      await refresh;
    });
    expect(result.current.providers).toEqual(settled);
  });
});
