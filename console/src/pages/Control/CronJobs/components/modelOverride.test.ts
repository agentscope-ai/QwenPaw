import { describe, expect, it } from "vitest";

import type { ProviderInfo } from "../../../../api/types";
import {
  applyModelOverrideToRequest,
  buildModelOverrideOptions,
  modelOverrideToFormValue,
} from "./modelOverride";

function makeProvider(overrides: Record<string, unknown> = {}): ProviderInfo {
  return {
    id: "dashscope",
    name: "DashScope",
    models: [],
    extra_models: [],
    ...overrides,
  } as unknown as ProviderInfo;
}

describe("buildModelOverrideOptions", () => {
  it("flattens provider models into provider_id:model options", () => {
    const providers = [
      makeProvider({
        id: "dashscope",
        name: "DashScope",
        models: [
          { id: "qwen3-max", name: "Qwen3 Max" },
          { id: "qwen3-plus", name: "" },
        ],
        extra_models: [{ id: "qwen-custom", name: "Custom" }],
      }),
      makeProvider({
        id: "openai",
        name: "OpenAI",
        models: [{ id: "gpt-5", name: "GPT-5" }],
      }),
    ] as unknown as ProviderInfo[];

    const options = buildModelOverrideOptions(providers);

    expect(options).toHaveLength(4);
    expect(options.map((o) => o.value).sort()).toEqual([
      "dashscope:qwen-custom",
      "dashscope:qwen3-max",
      "dashscope:qwen3-plus",
      "openai:gpt-5",
    ]);
    // Falls back to model id when display name is empty.
    const plus = options.find((o) => o.value === "dashscope:qwen3-plus");
    expect(plus?.label).toBe("DashScope / qwen3-plus");
  });

  it("dedupes models repeated across models/extra_models", () => {
    const providers = [
      makeProvider({
        models: [{ id: "m1", name: "M1" }],
        extra_models: [{ id: "m1", name: "M1 dup" }],
      }),
    ] as unknown as ProviderInfo[];

    expect(buildModelOverrideOptions(providers)).toHaveLength(1);
  });

  it("handles null/empty input", () => {
    expect(buildModelOverrideOptions(null)).toEqual([]);
    expect(buildModelOverrideOptions([])).toEqual([]);
  });
});

describe("modelOverrideToFormValue", () => {
  it("passes through a trimmed string value", () => {
    expect(modelOverrideToFormValue("  dashscope:qwen3-max ")).toBe(
      "dashscope:qwen3-max",
    );
  });

  it("converts a dict value to the string form", () => {
    expect(
      modelOverrideToFormValue({ provider_id: "openai", model: "gpt-5" }),
    ).toBe("openai:gpt-5");
  });

  it("keeps colons inside the model name", () => {
    expect(
      modelOverrideToFormValue({
        provider_id: "openrouter",
        model: "anthropic/claude:beta",
      }),
    ).toBe("openrouter:anthropic/claude:beta");
  });

  it("returns undefined for empty or unusable values", () => {
    expect(modelOverrideToFormValue("")).toBeUndefined();
    expect(modelOverrideToFormValue("   ")).toBeUndefined();
    expect(modelOverrideToFormValue(undefined)).toBeUndefined();
    expect(modelOverrideToFormValue(null)).toBeUndefined();
    expect(modelOverrideToFormValue({ provider_id: "openai" })).toBeUndefined();
    expect(modelOverrideToFormValue({ model: "gpt-5" })).toBeUndefined();
  });
});

describe("applyModelOverrideToRequest", () => {
  it("writes the normalized string into request.model_slot_override", () => {
    const request: Record<string, unknown> = { input: [] };
    applyModelOverrideToRequest(request, " dashscope:qwen3-max ");
    expect(request.model_slot_override).toBe("dashscope:qwen3-max");
  });

  it("removes the key when the value is cleared", () => {
    const request: Record<string, unknown> = {
      input: [],
      model_slot_override: "dashscope:qwen3-max",
    };
    applyModelOverrideToRequest(request, undefined);
    expect("model_slot_override" in request).toBe(false);
  });

  it("removes the key for blank strings", () => {
    const request: Record<string, unknown> = {
      model_slot_override: "dashscope:qwen3-max",
    };
    applyModelOverrideToRequest(request, "   ");
    expect("model_slot_override" in request).toBe(false);
  });

  it("is a no-op when request is undefined", () => {
    expect(() => applyModelOverrideToRequest(undefined, "a:b")).not.toThrow();
  });
});
