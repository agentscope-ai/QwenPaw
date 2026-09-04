import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ActiveModelsInfo, ProviderInfo } from "../../../api/types";
import { modelSelectorApi } from "./modelSelectorApi";
import { useModelSelectorData } from "./useModelSelectorData";

vi.mock("./modelSelectorApi", () => ({
  modelSelectorApi: {
    loadActiveModels: vi.fn(),
    loadModelSelectorData: vi.fn(),
  },
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}

describe("useModelSelectorData", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "visible",
    });
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

  it("refreshes the active model after the online event", async () => {
    const initialModels: ActiveModelsInfo = {
      active_llm: { provider_id: "openai", model: "gpt-old" },
    };
    const refreshedModels: ActiveModelsInfo = {
      active_llm: { provider_id: "openai", model: "gpt-new" },
    };
    vi.mocked(modelSelectorApi.loadModelSelectorData).mockResolvedValue({
      providers: [],
      activeModels: initialModels,
      loadError: false,
    });
    vi.mocked(modelSelectorApi.loadActiveModels).mockResolvedValue(
      refreshedModels,
    );
    const onActiveModels = vi.fn();
    const { result } = renderHook(() =>
      useModelSelectorData({ agentId: "default", onActiveModels }),
    );
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => {
      window.dispatchEvent(new Event("online"));
    });

    await waitFor(() => {
      expect(result.current.activeModels).toEqual(refreshedModels);
    });
  });

  it("refreshes after a persisted pageshow event", async () => {
    const initialModels: ActiveModelsInfo = {
      active_llm: { provider_id: "openai", model: "gpt-old" },
    };
    const refreshedModels: ActiveModelsInfo = {
      active_llm: { provider_id: "openai", model: "gpt-new" },
    };
    vi.mocked(modelSelectorApi.loadModelSelectorData).mockResolvedValue({
      providers: [],
      activeModels: initialModels,
      loadError: false,
    });
    vi.mocked(modelSelectorApi.loadActiveModels).mockResolvedValue(
      refreshedModels,
    );
    const onActiveModels = vi.fn();
    const { result } = renderHook(() =>
      useModelSelectorData({ agentId: "default", onActiveModels }),
    );
    await waitFor(() => expect(result.current.loading).toBe(false));

    const event = new Event("pageshow");
    Object.defineProperty(event, "persisted", { value: true });
    act(() => window.dispatchEvent(event));

    await waitFor(() => {
      expect(result.current.activeModels).toEqual(refreshedModels);
    });
  });

  it("does not refresh after a normal pageshow event", async () => {
    vi.mocked(modelSelectorApi.loadModelSelectorData).mockResolvedValue({
      providers: [],
      activeModels: null,
      loadError: false,
    });
    const onActiveModels = vi.fn();
    const { result } = renderHook(() =>
      useModelSelectorData({ agentId: "default", onActiveModels }),
    );
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => window.dispatchEvent(new Event("pageshow")));

    expect(modelSelectorApi.loadActiveModels).not.toHaveBeenCalled();
  });

  it("refreshes the active model when the page becomes visible", async () => {
    const initialModels: ActiveModelsInfo = {
      active_llm: { provider_id: "openai", model: "gpt-old" },
    };
    const refreshedModels: ActiveModelsInfo = {
      active_llm: { provider_id: "openai", model: "gpt-new" },
    };
    vi.mocked(modelSelectorApi.loadModelSelectorData).mockResolvedValue({
      providers: [],
      activeModels: initialModels,
      loadError: false,
    });
    vi.mocked(modelSelectorApi.loadActiveModels).mockResolvedValue(
      refreshedModels,
    );
    const onActiveModels = vi.fn();
    const { result } = renderHook(() =>
      useModelSelectorData({ agentId: "default", onActiveModels }),
    );
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });

    await waitFor(() => {
      expect(result.current.activeModels).toEqual(refreshedModels);
    });
  });

  it("keeps the last model when a recovery refresh fails", async () => {
    const initialModels: ActiveModelsInfo = {
      active_llm: { provider_id: "openai", model: "gpt-old" },
    };
    vi.mocked(modelSelectorApi.loadModelSelectorData).mockResolvedValue({
      providers: [],
      activeModels: initialModels,
      loadError: false,
    });
    vi.mocked(modelSelectorApi.loadActiveModels).mockRejectedValue(
      new Error("network"),
    );
    const onActiveModels = vi.fn();
    const { result } = renderHook(() =>
      useModelSelectorData({ agentId: "default", onActiveModels }),
    );
    await waitFor(() => {
      expect(result.current.activeModels).toEqual(initialModels);
    });

    act(() => {
      window.dispatchEvent(new Event("online"));
    });

    await waitFor(() => {
      expect(modelSelectorApi.loadActiveModels).toHaveBeenCalledOnce();
    });
    expect(result.current.activeModels).toEqual(initialModels);
  });

  it("applies an older initial result when a newer refresh fails", async () => {
    const initial = deferred<{
      providers: ProviderInfo[] | null;
      activeModels: ActiveModelsInfo | null;
      loadError: boolean;
    }>();
    const refresh = deferred<ActiveModelsInfo>();
    const initialModels: ActiveModelsInfo = {
      active_llm: { provider_id: "openai", model: "gpt-old" },
    };
    vi.mocked(modelSelectorApi.loadModelSelectorData).mockReturnValue(
      initial.promise,
    );
    vi.mocked(modelSelectorApi.loadActiveModels).mockReturnValue(
      refresh.promise,
    );
    const onActiveModels = vi.fn();
    const { result } = renderHook(() =>
      useModelSelectorData({ agentId: "default", onActiveModels }),
    );

    act(() => window.dispatchEvent(new Event("online")));
    refresh.reject(new Error("network"));
    initial.resolve({
      providers: [],
      activeModels: initialModels,
      loadError: false,
    });

    await waitFor(() => {
      expect(result.current.activeModels).toEqual(initialModels);
    });
    expect(onActiveModels).toHaveBeenCalledOnce();
  });

  it("does not let an older initial result overwrite a newer refresh", async () => {
    const initial = deferred<{
      providers: ProviderInfo[] | null;
      activeModels: ActiveModelsInfo | null;
      loadError: boolean;
    }>();
    const refreshedModels: ActiveModelsInfo = {
      active_llm: { provider_id: "openai", model: "gpt-new" },
    };
    vi.mocked(modelSelectorApi.loadModelSelectorData).mockReturnValue(
      initial.promise,
    );
    vi.mocked(modelSelectorApi.loadActiveModels).mockResolvedValue(
      refreshedModels,
    );
    const onActiveModels = vi.fn();
    const { result } = renderHook(() =>
      useModelSelectorData({ agentId: "default", onActiveModels }),
    );

    act(() => window.dispatchEvent(new Event("online")));
    await waitFor(() => {
      expect(result.current.activeModels).toEqual(refreshedModels);
    });
    initial.resolve({
      providers: [],
      activeModels: {
        active_llm: { provider_id: "openai", model: "gpt-old" },
      },
      loadError: false,
    });
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.activeModels).toEqual(refreshedModels);
    expect(onActiveModels).toHaveBeenCalledOnce();
  });

  it("does not let an older refresh overwrite an explicit model commit", async () => {
    const recovery = deferred<ActiveModelsInfo>();
    const committedModels: ActiveModelsInfo = {
      active_llm: { provider_id: "openai", model: "gpt-selected" },
    };
    vi.mocked(modelSelectorApi.loadModelSelectorData).mockResolvedValue({
      providers: [],
      activeModels: null,
      loadError: false,
    });
    vi.mocked(modelSelectorApi.loadActiveModels).mockReturnValue(
      recovery.promise,
    );
    const onActiveModels = vi.fn();
    const { result } = renderHook(() =>
      useModelSelectorData({ agentId: "default", onActiveModels }),
    );
    await waitFor(() => expect(result.current.loading).toBe(false));

    let refreshPromise: Promise<void>;
    act(() => {
      refreshPromise = result.current.refreshActiveModels();
    });
    act(() => result.current.commitActiveModels(committedModels));
    recovery.resolve({
      active_llm: { provider_id: "openai", model: "gpt-stale" },
    });
    await act(async () => refreshPromise);

    expect(result.current.activeModels).toEqual(committedModels);
    expect(onActiveModels).toHaveBeenCalledOnce();
    expect(onActiveModels).toHaveBeenCalledWith(committedModels);
  });

  it("does not apply an old agent result after the agent changes", async () => {
    const agentA = deferred<{
      providers: ProviderInfo[] | null;
      activeModels: ActiveModelsInfo | null;
      loadError: boolean;
    }>();
    const agentBModels: ActiveModelsInfo = {
      active_llm: { provider_id: "openai", model: "gpt-agent-b" },
    };
    vi.mocked(modelSelectorApi.loadModelSelectorData)
      .mockReturnValueOnce(agentA.promise)
      .mockResolvedValueOnce({
        providers: [],
        activeModels: agentBModels,
        loadError: false,
      });
    const onActiveModels = vi.fn();
    const { result, rerender } = renderHook(
      ({ agentId }) => useModelSelectorData({ agentId, onActiveModels }),
      { initialProps: { agentId: "agent-a" } },
    );

    rerender({ agentId: "agent-b" });
    await waitFor(() => {
      expect(result.current.activeModels).toEqual(agentBModels);
    });
    agentA.resolve({
      providers: [],
      activeModels: {
        active_llm: { provider_id: "openai", model: "gpt-agent-a" },
      },
      loadError: false,
    });
    await act(async () => agentA.promise);

    expect(result.current.activeModels).toEqual(agentBModels);
    expect(onActiveModels).toHaveBeenCalledOnce();
    expect(onActiveModels).toHaveBeenCalledWith(agentBModels);
  });

  it("coalesces concurrent recovery events", async () => {
    const refresh = deferred<ActiveModelsInfo>();
    vi.mocked(modelSelectorApi.loadModelSelectorData).mockResolvedValue({
      providers: [],
      activeModels: null,
      loadError: false,
    });
    vi.mocked(modelSelectorApi.loadActiveModels).mockReturnValue(
      refresh.promise,
    );
    const onActiveModels = vi.fn();
    renderHook(() =>
      useModelSelectorData({ agentId: "default", onActiveModels }),
    );
    await waitFor(() => {
      expect(modelSelectorApi.loadModelSelectorData).toHaveBeenCalledOnce();
    });

    act(() => {
      window.dispatchEvent(new Event("online"));
      document.dispatchEvent(new Event("visibilitychange"));
      const event = new Event("pageshow");
      Object.defineProperty(event, "persisted", { value: true });
      window.dispatchEvent(event);
    });

    expect(modelSelectorApi.loadActiveModels).toHaveBeenCalledOnce();
    refresh.resolve({
      active_llm: { provider_id: "openai", model: "gpt-new" },
    });
  });
});
