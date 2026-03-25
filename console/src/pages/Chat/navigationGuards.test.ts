import { describe, expect, it } from "vitest";
import { shouldAutoSyncChatUrl } from "./navigationGuards";

describe("shouldAutoSyncChatUrl", () => {
  it("returns true when current route has no explicit chat id", () => {
    expect(shouldAutoSyncChatUrl(undefined)).toBe(true);
    expect(shouldAutoSyncChatUrl("null")).toBe(true);
    expect(shouldAutoSyncChatUrl("undefined")).toBe(true);
  });

  it("returns false when current route already points to a concrete chat id", () => {
    expect(shouldAutoSyncChatUrl("1774266983372")).toBe(false);
    expect(shouldAutoSyncChatUrl("a4e4f741-a57b-4d95-8cdf-5f4ad8a9a22c")).toBe(
      false,
    );
  });
});
