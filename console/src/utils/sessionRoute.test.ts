import { describe, expect, it } from "vitest";

import { buildChatPath, getSessionIdFromPath } from "./sessionRoute";

describe("chat session routes", () => {
  it("builds and parses the unified chat route", () => {
    const path = buildChatPath("chat-123");

    expect(path).toBe("/chat/chat-123");
    expect(getSessionIdFromPath(path)).toBe("chat-123");
    expect(buildChatPath()).toBe("/chat");
  });

  it("resolves encoded notification links without decoding twice", () => {
    expect(getSessionIdFromPath("/chat/console%3Auser")).toBe("console:user");
    expect(getSessionIdFromPath("/chat/a%2520b")).toBe("a%20b");
    expect(getSessionIdFromPath("/chat/malformed%escape")).toBe(
      "malformed%escape",
    );
  });
});
