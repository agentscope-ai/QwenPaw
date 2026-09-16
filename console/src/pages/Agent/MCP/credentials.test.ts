import { describe, expect, it } from "vitest";
import {
  buildCredentialUpdates,
  createCredentialDraft,
  type CredentialDraft,
} from "./credentials";

describe("MCP credential drafts", () => {
  it("starts configured fields as keep without reconstructing secret values", () => {
    const draft = createCredentialDraft({
      headers: ["Authorization"],
      env: ["API_KEY"],
    });

    expect(draft).toEqual({
      headers: { Authorization: { action: "keep", value: "" } },
      env: { API_KEY: { action: "keep", value: "" } },
    });
  });

  it("serializes keep, replace, and delete explicitly", () => {
    const draft: CredentialDraft = {
      headers: {
        Authorization: { action: "keep", value: "" },
        "X-API-Key": { action: "replace", value: "new-secret" },
      },
      env: { OLD_TOKEN: { action: "delete", value: "" } },
    };

    expect(buildCredentialUpdates(draft)).toEqual({
      headers: {
        Authorization: { action: "keep" },
        "X-API-Key": { action: "replace", value: "new-secret" },
      },
      env: { OLD_TOKEN: { action: "delete" } },
    });
  });

  it("rejects an empty replacement", () => {
    expect(() =>
      buildCredentialUpdates({
        headers: { Authorization: { action: "replace", value: "" } },
        env: {},
      }),
    ).toThrow("credential replacement requires a value");
  });
});
