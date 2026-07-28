/**
 * Tests for page-path normalization used by lazy module registration.
 */
import { describe, expect, it } from "vitest";
import { pagePathToModuleKey } from "./dynamicModuleRegistry";

describe("pagePathToModuleKey", () => {
  it("normalizes TypeScript page module paths", () => {
    expect(pagePathToModuleKey("../pages/Settings/Debug/index.tsx")).toBe(
      "Settings/Debug/index",
    );
    expect(pagePathToModuleKey("../pages/Chat/utils.ts")).toBe("Chat/utils");
  });
});
