import { describe, it, expect } from "vitest";
import { INBOX_MESSAGE_SOURCE_TYPES } from "./useInboxData";

describe("useInboxData file baseline inbox visibility", () => {
  it("excludes file_baseline_protection from Messages tab source types", () => {
    expect(INBOX_MESSAGE_SOURCE_TYPES).not.toContain("file_baseline_protection");
  });
});
