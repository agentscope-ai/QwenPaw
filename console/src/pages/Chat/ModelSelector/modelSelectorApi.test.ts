import { describe, expect, it, vi } from "vitest";

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

  it("两个请求都成功时 loadError 为 false", async () => {
    const providers = [
      { id: "test", name: "Test", models: [], extra_models: [] },
    ];
    const activeModels = { active_llm: { provider_id: "test", model: "m1" } };
    const dataSource = {
      listProviders: vi.fn().mockResolvedValue(providers),
      getActiveModels: vi.fn().mockResolvedValue(activeModels),
    };

    const result = await loadModelSelectorData("default", dataSource);

    expect(result.loadError).toBe(false);
    expect(result.providers).toEqual(providers);
    expect(result.activeModels).toEqual(activeModels);
  });
});
