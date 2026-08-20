import { describe, expect, it } from "vitest";
import { LONG_CHAT_USER_MESSAGE_ANCHORS } from "./longChatPerformance";

describe("long chat performance configuration", () => {
  it("keeps the full-history anchor measurement disabled", () => {
    expect(LONG_CHAT_USER_MESSAGE_ANCHORS).toEqual({
      enabled: false,
      variant: "navigator",
    });
  });
});
