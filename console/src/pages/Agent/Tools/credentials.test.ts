import { describe, expect, it } from "vitest";
import { buildToolConfigUpdate } from "./credentials";
import type { ToolConfigField } from "../../../api/modules/tools";

const fields: ToolConfigField[] = [
  { name: "api_key", label: "API Key", type: "password", required: true },
  { name: "endpoint", label: "Endpoint", type: "text", required: false },
];

describe("buildToolConfigUpdate", () => {
  it("separates non-sensitive values from an explicit replacement", () => {
    expect(
      buildToolConfigUpdate(
        fields,
        { endpoint: "https://example.test", api_key: "must-not-copy" },
        { api_key: "replace" },
        { api_key: "new-secret" },
      ),
    ).toEqual({
      config: { endpoint: "https://example.test" },
      credential_updates: {
        api_key: { action: "replace", value: "new-secret" },
      },
    });
  });

  it("emits keep and delete without a value", () => {
    expect(buildToolConfigUpdate(fields, {}, { api_key: "keep" }, {})).toEqual({
      config: {},
      credential_updates: { api_key: { action: "keep" } },
    });
    expect(
      buildToolConfigUpdate(fields, {}, { api_key: "delete" }, {}),
    ).toEqual({
      config: {},
      credential_updates: { api_key: { action: "delete" } },
    });
  });

  it("rejects an empty replacement", () => {
    expect(() =>
      buildToolConfigUpdate(fields, {}, { api_key: "replace" }, {}),
    ).toThrow("api_key");
  });
});
