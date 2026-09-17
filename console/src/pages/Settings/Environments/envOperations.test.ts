import { describe, expect, it } from "vitest";

import { buildEnvOperations } from "./envOperations";

describe("buildEnvOperations", () => {
  it("keeps untouched saved values and replaces only edited or new rows", () => {
    expect(
      buildEnvOperations([
        { key: "SAVED", value: "", configured: true },
        {
          key: "EMPTY_REPLACEMENT",
          value: "",
          configured: true,
          valueChanged: true,
        },
        { key: "NEW_KEY", value: "new-secret", isNew: true },
      ]),
    ).toEqual([
      { key: "SAVED", action: "keep" },
      { key: "EMPTY_REPLACEMENT", action: "replace", value: "" },
      { key: "NEW_KEY", action: "replace", value: "new-secret" },
    ]);
  });
});
