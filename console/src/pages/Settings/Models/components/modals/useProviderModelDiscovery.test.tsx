import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import api from "../../../../../api";
import type {
  DiscoverModelsResponse,
  ProviderInfo,
} from "../../../../../api/types";
import { useProviderModelDiscovery } from "./useProviderModelDiscovery";

vi.mock("../../../../../api", () => ({
  default: {
    discoverModels: vi.fn(),
  },
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

function makeProvider(overrides: Partial<ProviderInfo> = {}): ProviderInfo {
  return {
    id: "custom",
    name: "Custom",
    models: [],
    extra_models: [],
    discovered_models: [],
    models_syncing: false,
    support_model_discovery: true,
    is_custom: true,
    is_local: false,
    api_key_prefix: "sk-",
    chat_model: "OpenAIChatModel",
    support_connection_check: false,
    freeze_url: false,
    require_api_key: true,
    api_key: "",
    base_url: "https://api.example/v1",
    generate_kwargs: {},
    ...overrides,
  };
}

function successfulDiscovery(modelId: string): DiscoverModelsResponse {
  return {
    success: true,
    message: "",
    models: [
      {
        id: modelId,
        name: modelId,
      },
    ] as ProviderInfo["models"],
    discovered_count: 1,
  };
}

const terminalOutcomes: Array<{
  error: string | null;
  name: string;
  overrides: Partial<ProviderInfo>;
  state: "empty" | "failed";
}> = [
  {
    error: null,
    name: "empty sync",
    overrides: {
      models_last_synced_at: "2026-08-28T00:00:00+00:00",
    },
    state: "empty",
  },
  {
    error: "Authentication failed",
    name: "failed sync",
    overrides: {
      models_last_sync_error: "Authentication failed",
    },
    state: "failed",
  },
];

describe("useProviderModelDiscovery", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("does not rediscover when a completed provider sync supplies models", async () => {
    const onSaved = vi.fn();
    const { result, rerender } = renderHook(
      ({ provider }) =>
        useProviderModelDiscovery({
          provider,
          autoPreview: true,
          fallbackError: "Discovery failed",
          onSaved,
        }),
      {
        initialProps: {
          provider: makeProvider({ models_syncing: true }),
        },
      },
    );

    rerender({
      provider: makeProvider({
        discovered_models: successfulDiscovery("remote").models,
        models_last_synced_at: "2026-08-28T00:00:00+00:00",
      }),
    });

    await waitFor(() => {
      expect(result.current.models.map((model) => model.id)).toEqual([
        "remote",
      ]);
    });
    expect(api.discoverModels).not.toHaveBeenCalled();
    expect(result.current.state).toBe("ready");
  });

  it.each(terminalOutcomes)(
    "does not rediscover after a completed $name",
    async ({ error, overrides, state }) => {
      const onSaved = vi.fn();
      const { result, rerender } = renderHook(
        ({ provider }) =>
          useProviderModelDiscovery({
            provider,
            autoPreview: true,
            fallbackError: "Discovery failed",
            onSaved,
          }),
        {
          initialProps: {
            provider: makeProvider({ models_syncing: true }),
          },
        },
      );

      rerender({ provider: makeProvider(overrides) });

      await waitFor(() => expect(result.current.state).toBe(state));
      expect(result.current.error).toBe(error);
      expect(api.discoverModels).not.toHaveBeenCalled();
    },
  );

  it.each(terminalOutcomes)(
    "allows manual refresh after a completed $name",
    async ({ overrides }) => {
      vi.mocked(api.discoverModels).mockResolvedValue(
        successfulDiscovery("refreshed"),
      );
      const onSaved = vi.fn();
      const provider = makeProvider(overrides);
      const { result } = renderHook(() =>
        useProviderModelDiscovery({
          provider,
          autoPreview: true,
          fallbackError: "Discovery failed",
          onSaved,
        }),
      );

      expect(api.discoverModels).not.toHaveBeenCalled();
      await act(async () => {
        await result.current.discover();
      });

      expect(api.discoverModels).toHaveBeenCalledOnce();
      expect(result.current.state).toBe("ready");
      expect(result.current.models.map((model) => model.id)).toEqual([
        "refreshed",
      ]);
      expect(onSaved).toHaveBeenCalledOnce();
    },
  );

  it("reuses the in-flight preview discovery", async () => {
    const pending = deferred<DiscoverModelsResponse>();
    vi.mocked(api.discoverModels).mockReturnValue(pending.promise);
    const onSaved = vi.fn();
    const { result } = renderHook(() =>
      useProviderModelDiscovery({
        provider: makeProvider(),
        autoPreview: true,
        fallbackError: "Discovery failed",
        onSaved,
      }),
    );

    await waitFor(() => expect(api.discoverModels).toHaveBeenCalledOnce());
    act(() => {
      void result.current.discover();
    });
    expect(api.discoverModels).toHaveBeenCalledOnce();

    await act(async () => {
      pending.resolve(successfulDiscovery("remote"));
      await pending.promise;
    });
    await waitFor(() => expect(result.current.state).toBe("ready"));
    expect(onSaved).toHaveBeenCalledOnce();
  });

  it("ignores a discovery response after the provider changes", async () => {
    const pending = deferred<DiscoverModelsResponse>();
    vi.mocked(api.discoverModels).mockReturnValue(pending.promise);
    const onSaved = vi.fn();
    const { result, rerender } = renderHook(
      ({ provider }) =>
        useProviderModelDiscovery({
          provider,
          autoPreview: false,
          fallbackError: "Discovery failed",
          onSaved,
        }),
      { initialProps: { provider: makeProvider() } },
    );

    act(() => {
      void result.current.discover();
    });
    rerender({
      provider: makeProvider({
        id: "other",
        discovered_models: successfulDiscovery("other-model").models,
      }),
    });

    await act(async () => {
      pending.resolve(successfulDiscovery("stale-model"));
      await pending.promise;
    });
    expect(result.current.models.map((model) => model.id)).toEqual([
      "other-model",
    ]);
    expect(onSaved).not.toHaveBeenCalled();
  });

  it("ignores a discovery response after the provider revision changes", async () => {
    const pending = deferred<DiscoverModelsResponse>();
    vi.mocked(api.discoverModels).mockReturnValue(pending.promise);
    const onSaved = vi.fn();
    const { result, rerender } = renderHook(
      ({ provider }) =>
        useProviderModelDiscovery({
          provider,
          autoPreview: false,
          fallbackError: "Discovery failed",
          onSaved,
        }),
      {
        initialProps: {
          provider: makeProvider({
            meta: { provider_runtime_revision: 0 },
          }),
        },
      },
    );

    act(() => {
      void result.current.discover();
    });
    rerender({
      provider: makeProvider({
        discovered_models: successfulDiscovery("new-model").models,
        meta: { provider_runtime_revision: 1 },
      }),
    });

    await act(async () => {
      pending.resolve(successfulDiscovery("stale-model"));
      await pending.promise;
    });
    expect(result.current.models.map((model) => model.id)).toEqual([
      "new-model",
    ]);
    expect(onSaved).not.toHaveBeenCalled();
  });
});
