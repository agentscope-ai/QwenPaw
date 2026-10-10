import { describe, it, expect } from "vitest";
import {
  buildEligibleProviders,
  modelKey,
  splitProvidersByTier,
} from "./modelSelectorModels";
import type { ProviderInfo } from "../../../api/types";

function makeModel(
  id: string,
  maxInputLength: number,
): ProviderInfo["models"][number] {
  return {
    id,
    name: id,
    supports_multimodal: false,
    supports_image: false,
    supports_video: false,
    max_output_length: 4096,
    max_input_length: maxInputLength,
    generate_kwargs: {},
    relay_reasoning: false,
    thinking_enabled: null,
    thinking_budget: null,
    reasoning_effort: null,
  };
}

function makeProvider(overrides: Partial<ProviderInfo>): ProviderInfo {
  return {
    id: "test-provider",
    name: "Test Provider",
    api_key_prefix: "test",
    chat_model: "test-model",
    models: [],
    extra_models: [],
    is_custom: false,
    is_local: false,
    support_model_discovery: false,
    support_connection_check: false,
    freeze_url: false,
    require_api_key: true,
    api_key: "sk-test",
    base_url: "https://api.test.com",
    generate_kwargs: {},
    ...overrides,
  };
}

describe("modelSelectorModels (#5784 压缩阈值跨 provider 校验)", () => {
  describe("modelKey", () => {
    it("由 provider_id:model_id 组成唯一键", () => {
      expect(modelKey("dashscope", "qwen-max")).toBe("dashscope:qwen-max");
      expect(modelKey("openai", "qwen-max")).toBe("openai:qwen-max");
      // same model name under different providers gets a different key
      expect(modelKey("dashscope", "qwen-max")).not.toBe(
        modelKey("openai", "qwen-max"),
      );
    });
  });

  describe("buildEligibleProviders", () => {
    it("两个 provider 有同名 model 时，各自保留自己的 max_input_length", () => {
      const sharedModelId = "shared-model";
      const providers: ProviderInfo[] = [
        makeProvider({
          id: "provider-a",
          name: "Provider A",
          models: [makeModel(sharedModelId, 32768)],
        }),
        makeProvider({
          id: "provider-b",
          name: "Provider B",
          models: [makeModel(sharedModelId, 131072)],
        }),
      ];

      const eligible = buildEligibleProviders(providers);
      expect(eligible).toHaveLength(2);

      const modelA = eligible
        .find((p) => p.id === "provider-a")!
        .models.find((m) => m.id === sharedModelId)!;
      const modelB = eligible
        .find((p) => p.id === "provider-b")!
        .models.find((m) => m.id === sharedModelId)!;

      // Key assertion: same model name under different providers keeps its own max_input_length
      expect(modelA.max_input_length).toBe(32768);
      expect(modelB.max_input_length).toBe(131072);
    });

    it("effective_max_input_length 应取匹配 provider_id + model_id 的值", () => {
      // backend effective_max_input_length is matched by provider + model
      const providers: ProviderInfo[] = [
        makeProvider({
          id: "dashscope",
          name: "DashScope",
          models: [makeModel("qwen-max", 32768)],
        }),
        makeProvider({
          id: "openai",
          name: "OpenAI",
          models: [makeModel("qwen-max", 128000)],
        }),
      ];

      const eligible = buildEligibleProviders(providers);

      // active model dashscope:qwen-max -> effective_max_input_length 32768
      const dashscopeProvider = eligible.find((p) => p.id === "dashscope")!;
      const dashscopeModel = dashscopeProvider.models.find(
        (m) => m.id === "qwen-max",
      )!;
      expect(dashscopeModel.max_input_length).toBe(32768);

      // active model openai:qwen-max -> effective_max_input_length 128000
      const openaiProvider = eligible.find((p) => p.id === "openai")!;
      const openaiModel = openaiProvider.models.find(
        (m) => m.id === "qwen-max",
      )!;
      expect(openaiModel.max_input_length).toBe(128000);
    });

    it("models 和 extra_models 合并后不丢失 provider 归属", () => {
      const providers: ProviderInfo[] = [
        makeProvider({
          id: "provider-x",
          name: "Provider X",
          models: [makeModel("model-1", 16384)],
          extra_models: [makeModel("model-2", 65536)],
        }),
      ];

      const eligible = buildEligibleProviders(providers);
      expect(eligible[0].models).toHaveLength(2);
      expect(
        eligible[0].models.find((m) => m.id === "model-1")!.max_input_length,
      ).toBe(16384);
      expect(
        eligible[0].models.find((m) => m.id === "model-2")!.max_input_length,
      ).toBe(65536);
    });

    it("无 api_key 且 require_api_key 的 provider 被排除", () => {
      const providers: ProviderInfo[] = [
        makeProvider({
          id: "no-key",
          name: "No Key Provider",
          api_key: "",
          require_api_key: true,
          models: [makeModel("model-1", 32768)],
        }),
      ];

      const eligible = buildEligibleProviders(providers);
      expect(eligible).toHaveLength(0);
    });

    it("is_free_tier provider 即使无 model 也保留", () => {
      const providers: ProviderInfo[] = [
        makeProvider({
          id: "free",
          name: "Free Provider",
          is_free_tier: true,
          models: [],
          extra_models: [],
          api_key: "",
          require_api_key: true,
        }),
      ];

      const eligible = buildEligibleProviders(providers);
      expect(eligible).toHaveLength(1);
      expect(eligible[0].id).toBe("free");
    });
  });

  describe("splitProvidersByTier", () => {
    it("keeps free models out of the PRO group", () => {
      const provider = makeProvider({
        id: "free-tier",
        name: "Free Tier Provider",
        is_free_tier: true,
        models: [
          { ...makeModel("free-model", 32768), is_free: true },
          { ...makeModel("paid-model", 65536), is_free: false },
        ],
      });

      const { freeProviders, proProviders } = splitProvidersByTier(
        buildEligibleProviders([provider]),
      );

      expect(freeProviders[0].models.map((model) => model.id)).toEqual([
        "free-model",
      ]);
      expect(proProviders[0].models.map((model) => model.id)).toEqual([
        "paid-model",
      ]);
    });
  });
});
