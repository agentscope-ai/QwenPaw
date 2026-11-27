import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ActiveModelsInfo, ProviderInfo } from "../../../api/types";
import { providerApi } from "../../../api/modules/provider";
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
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

describe("useModelSelectorData", () => {
  beforeEach(() => {
    vi.clearAllMocks();
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
    vi.spyOn(providerApi, "listProviders").mockResolvedValueOnce(providers);
    vi.mocked(modelSelectorApi.loadModelSelectorData).mockImplementation(
      async (_agent, source, _session, onProviders, onActiveModels) => {
        onProviders?.(await source!.listProviders());
        return initial.promise.then((result) => {
          if (result.activeModels) onActiveModels?.(result.activeModels);
          return result;
        });
      },
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
});

it("keeps the post-mutation catalog when an older refresh resolves late", async () => {
  const before = [{ id: "p", models: [{ id: "removed" }] }] as ProviderInfo[];
  const after = [{ id: "p", models: [] }] as unknown as ProviderInfo[];
  const refreshed = [{ id: "p", models: [{ id: "added" }] }] as ProviderInfo[];
  const older = deferred<ProviderInfo[]>();
  const listProviders = vi
    .spyOn(providerApi, "listProviders")
    .mockReset()
    .mockResolvedValueOnce(before)
    .mockReturnValueOnce(older.promise)
    .mockResolvedValueOnce(refreshed);
  vi.mocked(modelSelectorApi.loadModelSelectorData).mockImplementation(
    async (_agent, source, _session, onProviders) => {
      const providers = await source!.listProviders();
      onProviders?.(providers);
      return { providers, activeModels: null, loadError: false };
    },
  );
  const onActiveModels = vi.fn();
  const { result } = renderHook(() =>
    useModelSelectorData({ agentId: "default", onActiveModels }),
  );
  await waitFor(() => expect(result.current.providers).toEqual(before));

  let oldRefresh: ReturnType<typeof result.current.fetchData>;
  act(() => {
    oldRefresh = result.current.fetchData();
  });
  act(() => result.current.setProviders(after));
  await act(async () => {
    const refresh = result.current.fetchData();
    expect(listProviders).toHaveBeenCalledTimes(3);
    await refresh;
  });
  await act(async () => {
    older.resolve(before);
    await oldRefresh;
  });
  expect(result.current.providers).toEqual(refreshed);
});

it("restores the selected session model and discards late previous results", async () => {
  const old =
    deferred<
      Awaited<ReturnType<typeof modelSelectorApi.loadModelSelectorData>>
    >();
  vi.mocked(modelSelectorApi.loadModelSelectorData).mockImplementation(
    (_agent, _source, scope, _onProviders, onActiveModels) => {
      const response =
        scope?.sessionId === "one"
          ? old.promise
          : Promise.resolve({
              providers: [],
              loadError: false,
              activeModels: {
                active_llm: { provider_id: "p", model: "second" },
              },
            });
      return response.then((result) => {
        if (result.activeModels) onActiveModels?.(result.activeModels);
        return result;
      });
    },
  );
  const onActiveModels = vi.fn();
  const { result, rerender } = renderHook(
    ({ sessionId }) =>
      useModelSelectorData({
        agentId: "a",
        session: { sessionId, chatId: sessionId },
        onActiveModels,
      }),
    { initialProps: { sessionId: "one" } },
  );
  rerender({ sessionId: "two" });
  await waitFor(() =>
    expect(result.current.activeModels?.active_llm?.model).toBe("second"),
  );
  await act(async () =>
    old.resolve({
      providers: [],
      loadError: false,
      activeModels: { active_llm: { provider_id: "p", model: "first" } },
    }),
  );
  expect(result.current.activeModels?.active_llm?.model).toBe("second");
  expect(onActiveModels).toHaveBeenCalledTimes(1);
});
