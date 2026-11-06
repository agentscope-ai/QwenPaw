import { describe, expect, it, vi } from "vitest";

import type { ProviderInfo } from "../../../api/types";
import { loadModelSelectorData } from "./modelSelectorApi";

describe("loadModelSelectorData", () => {
  it("does not replace providers when their request fails", async () => {
    const activeModels = { active_llm: null };
    const dataSource = {
      listProviders: vi
        .fn()
        .mockRejectedValue(new Error("providers unavailable")),
      getActiveModels: vi.fn().mockResolvedValue(activeModels),
    };

    const result = await loadModelSelectorData("default", dataSource);

    expect(result).toEqual({
      providers: null,
      activeModels,
      loadError: true,
    });
  });

  // A#85049052: missing model config must not fail silently
  it("active models 请求失败时标记 loadError 而非静默忽略", async () => {
    const providers = [
      {
        id: "openai",
        name: "OpenAI",
        models: [{ id: "gpt-4", name: "GPT-4" }],
        extra_models: [],
      },
    ];
    const dataSource = {
      listProviders: vi.fn().mockResolvedValue(providers),
      getActiveModels: vi
        .fn()
        .mockRejectedValue(new Error("MODEL_CONFIG_MISSING")),
    };

    const result = await loadModelSelectorData("default", dataSource);

    // Key assertion: an active-models failure must set loadError even when providers succeed
    expect(result.loadError).toBe(true);
    expect(result.providers).toEqual(providers);
    expect(result.activeModels).toBeNull();
  });

  it("两个请求都失败时 loadError 为 true 且数据为 null", async () => {
    const dataSource = {
      listProviders: vi
        .fn()
        .mockRejectedValue(new Error("providers unavailable")),
      getActiveModels: vi
        .fn()
        .mockRejectedValue(new Error("active models unavailable")),
    };

    const result = await loadModelSelectorData("default", dataSource);

    expect(result.loadError).toBe(true);
    expect(result.providers).toBeNull();
    expect(result.activeModels).toBeNull();
  });

  it("publishes the active model before the provider catalog finishes", async () => {
    const providers: ProviderInfo[] = [
      {
        id: "test",
        name: "Test",
        models: [],
        extra_models: [],
        api_key_prefix: "",
        chat_model: "",
        is_custom: false,
        is_local: false,
        support_model_discovery: false,
        support_connection_check: false,
        freeze_url: false,
        require_api_key: false,
        api_key: "",
        base_url: "",
        generate_kwargs: {},
      },
    ];
    const activeModels = { active_llm: { provider_id: "test", model: "m1" } };
    let resolveProviders!: (value: typeof providers) => void;
    const onActiveModels = vi.fn();
    const dataSource = {
      listProviders: vi.fn(
        () =>
          new Promise<typeof providers>((resolve) => {
            resolveProviders = resolve;
          }),
      ),
      getActiveModels: vi.fn().mockResolvedValue(activeModels),
    };

    const loading = loadModelSelectorData(
      "default",
      dataSource,
      undefined,
      undefined,
      onActiveModels,
    );
    await vi.waitFor(() =>
      expect(onActiveModels).toHaveBeenCalledWith(activeModels),
    );
    resolveProviders(providers);
    const result = await loading;

    expect(result.loadError).toBe(false);
    expect(result.providers).toEqual(providers);
    expect(result.activeModels).toEqual(activeModels);
  });
});
