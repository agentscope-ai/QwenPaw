import { describe, it, expect } from "vitest";

import type { RerankerConfig } from "@/api/types/agent";
import {
  getRerankerServiceFingerprint,
  isRerankerConfigured,
} from "./rerankerUtils";

const enabledConfig: RerankerConfig = {
  enabled: true,
  api_key: "secret",
  base_url: "https://api.siliconflow.cn/v1/",
  model_name: "BAAI/bge-reranker-v2-m3",
  candidate_multiplier: 3,
  timeout: 10,
  auto_verify_interval_hours: 0,
};

describe("isRerankerConfigured", () => {
  it("requires the switch, base URL and model name", () => {
    expect(isRerankerConfigured(enabledConfig)).toBe(true);
    expect(
      isRerankerConfigured({ ...enabledConfig, enabled: false }),
    ).toBe(false);
    expect(isRerankerConfigured({ ...enabledConfig, base_url: " " })).toBe(
      false,
    );
    expect(
      isRerankerConfigured({ ...enabledConfig, model_name: "" }),
    ).toBe(false);
  });

  it("treats a missing config as not configured", () => {
    expect(isRerankerConfigured(undefined)).toBe(false);
  });

  it("mirrors load_reranker_config: api_key stays optional", () => {
    expect(isRerankerConfigured({ ...enabledConfig, api_key: "" })).toBe(
      true,
    );
  });
});

describe("getRerankerServiceFingerprint", () => {
  it("ignores trailing slashes in the base URL", () => {
    const withSlash = getRerankerServiceFingerprint(enabledConfig);
    const withoutSlash = getRerankerServiceFingerprint({
      ...enabledConfig,
      base_url: "https://api.siliconflow.cn/v1",
    });

    expect(withSlash).toBe(withoutSlash);
  });

  it("changes whenever a service-affecting field changes", () => {
    const baseline = getRerankerServiceFingerprint(enabledConfig);

    expect(
      getRerankerServiceFingerprint({ ...enabledConfig, api_key: "other" }),
    ).not.toBe(baseline);
    expect(
      getRerankerServiceFingerprint({
        ...enabledConfig,
        model_name: "other-model",
      }),
    ).not.toBe(baseline);
    expect(
      getRerankerServiceFingerprint({ ...enabledConfig, timeout: 5 }),
    ).not.toBe(baseline);
  });

  it("ignores form-only fields like the multiplier", () => {
    const baseline = getRerankerServiceFingerprint(enabledConfig);

    expect(
      getRerankerServiceFingerprint({
        ...enabledConfig,
        candidate_multiplier: 5,
      }),
    ).toBe(baseline);
  });

  it("returns an empty fingerprint for a missing config", () => {
    expect(getRerankerServiceFingerprint(undefined)).toBe("");
  });
});
