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
});
