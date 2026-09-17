/**
 * Tests for the Coding editor's extension → Monaco language mapping.
 */

import { describe, expect, it } from "vitest";

import { getLanguage } from "./getLanguage";

describe("getLanguage", () => {
  it("maps RobotFramework extensions", () => {
    expect(getLanguage("tests/login.robot")).toBe("robotframework");
    expect(getLanguage("resources/common.resource")).toBe("robotframework");
    expect(getLanguage("SUITE.ROBOT")).toBe("robotframework");
  });

  it("keeps existing mappings intact", () => {
    expect(getLanguage("main.py")).toBe("python");
    expect(getLanguage("app.tsx")).toBe("typescript");
    expect(getLanguage("unknown.xyz")).toBe("plaintext");
  });
});
