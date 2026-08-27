import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ActiveModelsInfo, ProviderInfo } from "../../../api/types";
import { modelSelectorApi } from "./modelSelectorApi";
import { useModelSelectorData } from "./useModelSelectorData";

vi.mock("./modelSelectorApi", () => ({
  modelSelectorApi: {
    loadActiveModels: vi.fn(),
    loadModelSelectorData: vi.fn(),
    loadProviders: vi.fn(),
  },
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

describe("useModelSelectorData", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("keeps initial providers when active refresh finishes first", async () => {
    const initial = deferred<{
      providers: ProviderInfo[] | null;
      activeModels: ActiveModelsInfo | null;
      loadError: boolean;
    }>();
    const refreshed: ActiveModelsInfo = {
      active_llm: { provider_id: "openai", model: "gpt-new" },
    };
    const providers = [
      {
        id: "openai",
        name: "OpenAI",
      } as ProviderInfo,
    ];
    vi.mocked(modelSelectorApi.loadModelSelectorData).mockReturnValue(
      initial.promise,
    );
    vi.mocked(modelSelectorApi.loadActiveModels).mockResolvedValue(refreshed);
    const onActiveModels = vi.fn();
    const { result } = renderHook(() =>
      useModelSelectorData({ agentId: "default", onActiveModels }),
    );

    await act(async () => {
      await result.current.refreshActiveModels();
    });
    initial.resolve({
      providers,
      activeModels: {
        active_llm: { provider_id: "openai", model: "gpt-old" },
      },
      loadError: false,
    });

    await waitFor(() => {
      expect(result.current.providers).toEqual(providers);
      expect(result.current.loading).toBe(false);
    });
    expect(result.current.activeModels).toEqual(refreshed);
    expect(onActiveModels).toHaveBeenCalledTimes(1);
    expect(onActiveModels).toHaveBeenCalledWith(refreshed);
  });

  it("polls only providers while discovery is running", async () => {
    vi.useFakeTimers();
    const syncing = [
      { id: "custom", name: "Custom", models_syncing: true },
    ] as ProviderInfo[];
    const settled = [
      {
        id: "custom",
        name: "Custom",
        models_syncing: false,
        discovered_models: [{ id: "remote", name: "Remote" }],
      },
    ] as ProviderInfo[];
    vi.mocked(modelSelectorApi.loadModelSelectorData).mockResolvedValue({
      providers: syncing,
      activeModels: null,
      loadError: false,
    });
    vi.mocked(modelSelectorApi.loadProviders).mockResolvedValue(settled);

    const onActiveModels = vi.fn();
    const { result } = renderHook(() =>
      useModelSelectorData({
        agentId: "default",
        onActiveModels,
      }),
    );

    await act(async () => {
      await Promise.resolve();
    });
    expect(result.current.providers).toEqual(syncing);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    expect(result.current.providers).toEqual(settled);
    expect(modelSelectorApi.loadModelSelectorData).toHaveBeenCalledOnce();
    expect(modelSelectorApi.loadProviders).toHaveBeenCalledOnce();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(modelSelectorApi.loadProviders).toHaveBeenCalledOnce();
  });

  it("does not overlap a pending provider poll", async () => {
    const syncing = [
      { id: "custom", name: "Custom", models_syncing: true },
    ] as ProviderInfo[];
    const settled = [
      { id: "custom", name: "Custom", models_syncing: false },
    ] as ProviderInfo[];
    const firstPoll = deferred<ProviderInfo[]>();
    vi.mocked(modelSelectorApi.loadModelSelectorData).mockResolvedValue({
      providers: syncing,
      activeModels: null,
      loadError: false,
    });
    vi.mocked(modelSelectorApi.loadProviders).mockReturnValue(
      firstPoll.promise,
    );

    const onActiveModels = vi.fn();
    const { unmount } = renderHook(() =>
      useModelSelectorData({ agentId: "default", onActiveModels }),
    );
    await waitFor(
      () => {
        expect(modelSelectorApi.loadProviders).toHaveBeenCalledOnce();
      },
      {
        timeout: 2000,
      },
    );

    await new Promise((resolve) => {
      window.setTimeout(resolve, 1100);
    });
    expect(modelSelectorApi.loadProviders).toHaveBeenCalledOnce();

    await act(async () => {
      firstPoll.resolve(settled);
      await firstPoll.promise;
      await Promise.resolve();
    });
    expect(modelSelectorApi.loadProviders).toHaveBeenCalledOnce();
    unmount();
  });

  it("keeps full-load active data when a provider poll finishes first", async () => {
    vi.useFakeTimers();
    const syncing = [
      { id: "custom", name: "Custom", models_syncing: true },
    ] as ProviderInfo[];
    const settled = [
      { id: "custom", name: "Custom", models_syncing: false },
    ] as ProviderInfo[];
    const refresh = deferred<{
      providers: ProviderInfo[] | null;
      activeModels: ActiveModelsInfo | null;
      loadError: boolean;
    }>();
    const activeModels: ActiveModelsInfo = {
      active_llm: { provider_id: "openai", model: "gpt-current" },
    };
    vi.mocked(modelSelectorApi.loadModelSelectorData)
      .mockResolvedValueOnce({
        providers: syncing,
        activeModels: null,
        loadError: false,
      })
      .mockReturnValueOnce(refresh.promise);
    vi.mocked(modelSelectorApi.loadProviders).mockResolvedValue(settled);

    const onActiveModels = vi.fn();
    const { result } = renderHook(() =>
      useModelSelectorData({ agentId: "default", onActiveModels }),
    );
    await act(async () => {
      await Promise.resolve();
    });

    let refreshPromise: ReturnType<typeof result.current.fetchData>;
    act(() => {
      refreshPromise = result.current.fetchData();
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(result.current.providers).toEqual(settled);

    await act(async () => {
      refresh.resolve({
        providers: syncing,
        activeModels,
        loadError: false,
      });
      await refreshPromise;
    });

    expect(result.current.providers).toEqual(settled);
    expect(result.current.activeModels).toEqual(activeModels);
    expect(result.current.loading).toBe(false);
    expect(onActiveModels).toHaveBeenCalledWith(activeModels);
  });

  it("does not let an old full load overwrite a committed model", async () => {
    const initial = deferred<{
      providers: ProviderInfo[] | null;
      activeModels: ActiveModelsInfo | null;
      loadError: boolean;
    }>();
    const providers = [{ id: "openai", name: "OpenAI" } as ProviderInfo];
    const committed: ActiveModelsInfo = {
      active_llm: { provider_id: "openai", model: "gpt-new" },
    };
    vi.mocked(modelSelectorApi.loadModelSelectorData).mockReturnValue(
      initial.promise,
    );
    const onActiveModels = vi.fn();
    const { result } = renderHook(() =>
      useModelSelectorData({ agentId: "default", onActiveModels }),
    );

    await waitFor(() => {
      expect(modelSelectorApi.loadModelSelectorData).toHaveBeenCalledOnce();
    });
    act(() => {
      result.current.commitActiveModels(committed);
    });
    initial.resolve({
      providers,
      activeModels: {
        active_llm: { provider_id: "openai", model: "gpt-old" },
      },
      loadError: false,
    });

    await waitFor(() => {
      expect(result.current.providers).toEqual(providers);
      expect(result.current.loading).toBe(false);
    });
    expect(result.current.activeModels).toEqual(committed);
    expect(onActiveModels).not.toHaveBeenCalled();
  });
});
