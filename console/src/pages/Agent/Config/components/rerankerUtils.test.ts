import { describe, it, expect } from "vitest";

import type { RerankerConfig } from "@/api/types/agent";
import { getRerankerConfigKey, isRerankerConfigured } from "./rerankerUtils";

// Generated per run so no credential-like literal is committed.
const TEST_API_KEY = `probe-${crypto.randomUUID().replace(/-/g, "")}`;

const enabledConfig: RerankerConfig = {
  enabled: true,
  api_key: TEST_API_KEY,
  base_url: "https://api.siliconflow.cn/v1/",
  model_name: "BAAI/bge-reranker-v2-m3",
  candidate_multiplier: 3,
  timeout: 10,
  auto_verify_interval_hours: 0,
};

describe("isRerankerConfigured", () => {
  it("requires the switch, base URL and model name", () => {
    expect(isRerankerConfigured(enabledConfig)).toBe(true);
    expect(isRerankerConfigured({ ...enabledConfig, enabled: false })).toBe(
      false,
    );
    expect(isRerankerConfigured({ ...enabledConfig, base_url: " " })).toBe(
      false,
    );
    expect(isRerankerConfigured({ ...enabledConfig, model_name: "" })).toBe(
      false,
    );
  });

  it("treats a missing config as not configured", () => {
    expect(isRerankerConfigured(undefined)).toBe(false);
  });

  it("mirrors load_reranker_config: api_key stays optional", () => {
    expect(isRerankerConfigured({ ...enabledConfig, api_key: "" })).toBe(true);
  });
});

describe("getRerankerConfigKey", () => {
  it("is synchronous and needs no WebCrypto", () => {
    // `crypto.subtle` is unavailable on a plain-HTTP console served from a
    // non-loopback origin; this helper must work anyway.
    expect(typeof getRerankerConfigKey(enabledConfig)).toBe("string");
    expect(getRerankerConfigKey(enabledConfig)).toContain(
      "https://api.siliconflow.cn/v1",
    );
  });

  it("ignores trailing slashes in the base URL", () => {
    expect(getRerankerConfigKey(enabledConfig)).toBe(
      getRerankerConfigKey({
        ...enabledConfig,
        base_url: "https://api.siliconflow.cn/v1",
      }),
    );
  });

  it("changes whenever a service-affecting field changes", () => {
    const baseline = getRerankerConfigKey(enabledConfig);

    expect(getRerankerConfigKey({ ...enabledConfig, api_key: "other" })).not.toBe(
      baseline,
    );
    expect(
      getRerankerConfigKey({ ...enabledConfig, model_name: "other-model" }),
    ).not.toBe(baseline);
    expect(getRerankerConfigKey({ ...enabledConfig, timeout: 5 })).not.toBe(
      baseline,
    );
  });

  it("preserves fractional timeouts (1.5 != 1)", () => {
    expect(
      getRerankerConfigKey({ ...enabledConfig, timeout: 1.5 }),
    ).not.toBe(getRerankerConfigKey({ ...enabledConfig, timeout: 1 }));
  });

  it("ignores form-only fields like the multiplier", () => {
    expect(
      getRerankerConfigKey({ ...enabledConfig, candidate_multiplier: 5 }),
    ).toBe(getRerankerConfigKey(enabledConfig));
  });

  it("returns an empty key for a missing config", () => {
    expect(getRerankerConfigKey(undefined)).toBe("");
  });
});