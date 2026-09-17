import { describe, expect, it } from "vitest";

import { resolveAssistantDisplayName } from "./branding";

describe("resolveAssistantDisplayName", () => {
  it("uses the public product name as the default assistant name", () => {
    expect(resolveAssistantDisplayName()).toBe("WeldonAgent");
    expect(resolveAssistantDisplayName("   ")).toBe("WeldonAgent");
  });

  it("preserves an explicit agent display name", () => {
    expect(resolveAssistantDisplayName("QA Agent")).toBe("QA Agent");
  });
});
