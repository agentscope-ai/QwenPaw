import { describe, expect, it } from "vitest";

import { createDependencyInstallRequest } from "./dependencyInstall";

describe("createDependencyInstallRequest", () => {
  it("builds built-in and custom source requests", () => {
    expect(createDependencyInstallRequest("auto", "ignored")).toEqual({
      source: "auto",
    });
    expect(
      createDependencyInstallRequest(
        "custom",
        "  https://packages.example.com/simple/  ",
      ),
    ).toEqual({
      source: "custom",
      custom_index_url: "https://packages.example.com/simple/",
    });
  });

  it("rejects an invalid custom source", () => {
    expect(() =>
      createDependencyInstallRequest("custom", "ftp://example.com"),
    ).toThrow();
  });
});
