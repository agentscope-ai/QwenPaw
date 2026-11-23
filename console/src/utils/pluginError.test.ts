import type { TFunction } from "i18next";
import { describe, expect, it } from "vitest";
import { pluginErrorMessage } from "./pluginError";
import { PluginApiError } from "@/api/modules/plugin";

const t = ((key: string) => key) as TFunction;

describe("shared plugin dependency errors", () => {
  it.each([
    ["DEPENDENCY_ENVIRONMENT_AMBIGUOUS", "ambiguous"],
    [new Error("DEPENDENCY_METADATA_INVALID"), "invalidMetadata"],
    [{ code: "DEPENDENCY_NEW_REASON" }, "failed"],
  ])("explains a bare dependency failure", (error, key) => {
    expect(pluginErrorMessage(error, "fallback", t)).toBe(
      `pluginManager.dependencyErrors.${key}`,
    );
  });

  it("preserves actionable server instructions and other errors", () => {
    expect(
      pluginErrorMessage(
        new Error("DEPENDENCY_CONFLICT: disable the incompatible consumer"),
        "fallback",
        t,
      ),
    ).toBe("disable the incompatible consumer");
    expect(
      pluginErrorMessage(new Error("source unavailable"), "fallback", t),
    ).toBe("source unavailable");
    expect(pluginErrorMessage(null, "fallback", t)).toBe("fallback");
  });

  it("explains the structured installation response used by other plugins", () => {
    const error = new PluginApiError("DEPENDENCY_ENVIRONMENT_AMBIGUOUS", 409, {
      code: "DEPENDENCY_ENVIRONMENT_AMBIGUOUS",
      instructions: [
        "Review the dependency preparation error before retrying installation.",
      ],
    });
    expect(pluginErrorMessage(error, "fallback", t)).toBe(
      "pluginManager.dependencyErrors.ambiguous",
    );
    expect(error.code).toBe("DEPENDENCY_ENVIRONMENT_AMBIGUOUS");
  });
});
