import { describe, expect, it } from "vitest";
import type { ProviderInfo } from "@/api/types/provider";
import {
  countConfiguredProviders,
  getIsConfigured,
  groupProviders,
} from "./utils";

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

describe("getIsConfigured", () => {
  it("treats qwenpaw-local as always configured", () => {
    expect(
      getIsConfigured(provider({ id: "qwenpaw-local", require_api_key: true })),
    ).toBe(true);
  });

  it("treats a custom provider with base_url as configured (no api_key needed)", () => {
    expect(
      getIsConfigured(
        provider({ id: "x", is_custom: true, base_url: "http://x" }),
      ),
    ).toBe(true);
  });

  it("treats a provider that does not require an api key as configured", () => {
    expect(
      getIsConfigured(
        provider({ id: "x", require_api_key: false, api_key: "" }),
      ),
    ).toBe(true);
  });

  it("treats a provider with require_api_key=true and a non-empty api_key as configured", () => {
    expect(
      getIsConfigured(
        provider({ id: "x", require_api_key: true, api_key: "sk-xx" }),
      ),
    ).toBe(true);
  });

  it("returns false when api_key is required but missing", () => {
    expect(
      getIsConfigured(
        provider({ id: "x", require_api_key: true, api_key: "" }),
      ),
    ).toBe(false);
  });

  it("returns false for a non-custom provider without api_key when it is required", () => {
    expect(
      getIsConfigured(
        provider({
          id: "x",
          is_custom: true,
          base_url: "",
          require_api_key: true,
          api_key: "",
        }),
      ),
    ).toBe(false);
  });
});

describe("groupProviders", () => {
  it("groups providers that share a provider_group (>=2)", () => {
    const result = groupProviders([
      provider({
        id: "kimi-cn",
        provider_group: "kimi",
        provider_group_name: "Kimi",
      }),
      provider({
        id: "kimi-intl",
        provider_group: "kimi",
        provider_group_name: "Kimi",
      }),
    ]);
    expect(result.grouped).toHaveLength(1);
    expect(result.grouped[0].groupKey).toBe("kimi");
    expect(result.grouped[0].groupName).toBe("Kimi");
    expect(result.grouped[0].providers.map((p) => p.id)).toEqual([
      "kimi-cn",
      "kimi-intl",
    ]);
    expect(result.ungrouped).toEqual([]);
  });

  it("moves a single-member group to ungrouped", () => {
    const lone = provider({
      id: "a",
      provider_group: "g",
      provider_group_name: "G",
    });
    const result = groupProviders([lone]);
    expect(result.grouped).toEqual([]);
    expect(result.ungrouped.map((p) => p.id)).toEqual(["a"]);
  });

  it("falls back to provider_group as groupName when provider_group_name is missing", () => {
    const lone = provider({ id: "a", provider_group: "g1" });
    const result = groupProviders([lone]);
    expect(result.ungrouped).toHaveLength(1);
    // Re-run with two members to observe the group name fallback
    const result2 = groupProviders([
      provider({ id: "a", provider_group: "g1" }),
      provider({ id: "b", provider_group: "g1" }),
    ]);
    expect(result2.grouped[0].groupName).toBe("g1");
  });

  it("puts providers without provider_group into ungrouped", () => {
    const result = groupProviders([
      provider({ id: "a" }),
      provider({ id: "b" }),
    ]);
    expect(result.grouped).toEqual([]);
    expect(result.ungrouped.map((p) => p.id)).toEqual(["a", "b"]);
  });
});
