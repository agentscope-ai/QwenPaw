import { describe, expect, it } from "vitest";
import type { AgentsLLMRoutingConfig } from "../../../api/types";
import { mergeFallbackRoutingConfig } from "./fallbackRouting";

describe("mergeFallbackRoutingConfig", () => {
  it("preserves existing routing fields when saving global fallback", () => {
    const original: AgentsLLMRoutingConfig = {
      enabled: true,
      mode: "cloud_first",
      local: { provider_id: "local-provider", model: "local-model" },
      cloud: { provider_id: "cloud-provider", model: "cloud-model" },
      fallback: { enabled: false, models: [] },
    };

    const merged = mergeFallbackRoutingConfig(original, {
      enabled: true,
      models: [{ provider_id: "fallback-provider", model: "fallback-model" }],
    });

    expect(merged).toEqual({
      enabled: true,
      mode: "cloud_first",
      local: { provider_id: "local-provider", model: "local-model" },
      cloud: { provider_id: "cloud-provider", model: "cloud-model" },
      fallback: {
        enabled: true,
        models: [{ provider_id: "fallback-provider", model: "fallback-model" }],
      },
    });
  });
});
