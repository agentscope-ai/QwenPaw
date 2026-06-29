import { describe, expect, it } from "vitest";
import type { ProviderInfo } from "../../../api/types/provider";
import { countConfiguredProviders } from "./utils";

function provider(overrides: Partial<ProviderInfo>): ProviderInfo {
  return {
    id: "provider",
    name: "Provider",
    api_key_prefix: "",
    chat_model: "",
    models: [],
    extra_models: [],
    is_custom: false,
    is_local: false,
    support_model_discovery: false,
    support_connection_check: false,
    freeze_url: false,
    require_api_key: true,
    api_key: "",
    base_url: "",
    generate_kwargs: {},
    ...overrides,
  };
}

describe("countConfiguredProviders", () => {
  it("counts only configured providers inside grouped cloud provider cards", () => {
    const providers = [
      provider({
        id: "provider-cn",
        provider_group: "provider",
        api_key: "configured-key",
      }),
      provider({
        id: "provider-intl",
        provider_group: "provider",
        api_key: "",
      }),
    ];

    expect(countConfiguredProviders(providers)).toBe(1);
  });

  it("counts custom providers with a base URL as configured", () => {
    const providers = [
      provider({
        id: "custom-openai",
        is_custom: true,
        base_url: "https://example.test/v1",
      }),
    ];

    expect(countConfiguredProviders(providers)).toBe(1);
  });
});
