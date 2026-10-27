import { describe, expect, it } from "vitest";
import { getValidApiKeyPrefixes, validateApiKey } from "./apiKeyValidation";

// ---------------------------------------------------------------------------
// API key validation — regression for #79
// (the validation condition and its message were written backwards, so a
// correct key was rejected and a wrong-prefix key was accepted. The
// direction of the check is now nailed down by tests.)
// ---------------------------------------------------------------------------
describe("getValidApiKeyPrefixes", () => {
  it("prefers the prefix list over the single prefix", () => {
    expect(
      getValidApiKeyPrefixes({
        api_key_prefixes: ["sk-", "key-"],
        api_key_prefix: "other-",
      }),
    ).toEqual(["sk-", "key-"]);
  });

  it("falls back to the single prefix when the list is empty", () => {
    expect(
      getValidApiKeyPrefixes({ api_key_prefixes: [], api_key_prefix: "sk-" }),
    ).toEqual(["sk-"]);
  });

  it("returns an empty list when the provider has no constraints", () => {
    expect(getValidApiKeyPrefixes({})).toEqual([]);
    expect(getValidApiKeyPrefixes({ api_key_prefix: "" })).toEqual([]);
  });
});

describe("validateApiKey (#79)", () => {
  const PREFIXES = ["sk-"];

  it("accepts a key that starts with an allowed prefix", () => {
    expect(validateApiKey("sk-abc123", PREFIXES, "api_key")).toEqual({
      valid: true,
    });
  });

  it("rejects a key with the wrong prefix", () => {
    const result = validateApiKey("pk-wrong", PREFIXES, "api_key");
    expect(result.valid).toBe(false);
    if (!result.valid) {
      expect(result.prefix).toBe("sk-");
    }
  });

  it("accepts an empty value (keeping an existing key unchanged)", () => {
    expect(validateApiKey("", PREFIXES, "api_key")).toEqual({ valid: true });
    expect(validateApiKey(undefined, PREFIXES, "api_key")).toEqual({
      valid: true,
    });
  });

  it("accepts any value when the provider defines no prefix rules", () => {
    expect(validateApiKey("anything-goes", [], "api_key")).toEqual({
      valid: true,
    });
  });

  it("bypasses prefix checks in auth_token mode", () => {
    expect(validateApiKey("auth-token-value", PREFIXES, "auth_token")).toEqual({
      valid: true,
    });
  });

  it("accepts when the key matches any one of several prefixes", () => {
    const multi = ["sk-", "key-", "bearer-"];
    expect(validateApiKey("key-xyz", multi, "api_key")).toEqual({
      valid: true,
    });
    expect(validateApiKey("bearer-tok", multi, "api_key")).toEqual({
      valid: true,
    });
    const rejected = validateApiKey("nope", multi, "api_key");
    expect(rejected.valid).toBe(false);
    if (!rejected.valid) {
      expect(rejected.prefix).toBe("sk-, key-, bearer-");
    }
  });
});
