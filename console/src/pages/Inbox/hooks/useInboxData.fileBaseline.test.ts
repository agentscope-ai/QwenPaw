import { describe, it, expect } from "vitest";
import { INBOX_MESSAGE_SOURCE_TYPES } from "./useInboxData";

describe("useInboxData persona inbox visibility", () => {
  it("includes file_baseline_protection in Messages tab source types", () => {
    expect(INBOX_MESSAGE_SOURCE_TYPES).toContain("file_baseline_protection");
  });
});
