import { describe, expect, it } from "vitest";
import { LONG_CHAT_USER_MESSAGE_ANCHORS } from "./longChatPerformance";

describe("long chat performance configuration", () => {
  it("keeps lightweight user-message navigation enabled", () => {
    expect(LONG_CHAT_USER_MESSAGE_ANCHORS).toEqual({
      enabled: true,
      variant: "navigator",
    });
  });
});
