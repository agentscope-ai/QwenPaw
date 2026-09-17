import { describe, expect, it } from "vitest";
import {
  buildCredentialUpdate,
  buildCustomHeadersUpdate,
  buildBaseUrlUpdate,
} from "./providerCredentials";

describe("buildCredentialUpdate", () => {
  it("keeps the stored credential when the secret input is untouched", () => {
    expect(buildCredentialUpdate(undefined, false)).toEqual({});
    expect(buildCredentialUpdate("", false)).toEqual({});
  });

  it("replaces the stored credential only with a new secret", () => {
    expect(buildCredentialUpdate("new-secret", false)).toEqual({
      api_key: "new-secret",
    });
  });

  it("uses an explicit clear operation instead of an empty secret", () => {
    expect(buildCredentialUpdate(undefined, true)).toEqual({
      clear_api_key: true,
    });
  });

  it("never writes a legacy masked value as the credential", () => {
    expect(buildCredentialUpdate("sk-******", false)).toEqual({});
  });
});

describe("buildBaseUrlUpdate", () => {
  it("does not submit a projected URL when the field is untouched", () => {
    const projected = "https://example.invalid/?key=%5Bredacted%5D";
    expect(buildBaseUrlUpdate(projected, projected)).toEqual({});
  });

  it("submits a changed URL and explicitly clears an emptied URL", () => {
    expect(buildBaseUrlUpdate("https://new.invalid/v1", "https://old.invalid/v1")).toEqual({
      base_url: "https://new.invalid/v1",
    });
    expect(buildBaseUrlUpdate("", "https://old.invalid/v1")).toEqual({
      clear_base_url: true,
    });
  });
});

describe("buildCustomHeadersUpdate", () => {
  it("keeps hidden headers until the editor is changed", () => {
    expect(buildCustomHeadersUpdate({}, false)).toEqual({});
  });

  it("replaces or explicitly clears headers after an edit", () => {
    expect(buildCustomHeadersUpdate({ "X-Trace": "enabled" }, true)).toEqual({
      custom_headers: { "X-Trace": "enabled" },
    });
    expect(buildCustomHeadersUpdate({}, true)).toEqual({
      clear_custom_headers: true,
    });
  });
});
