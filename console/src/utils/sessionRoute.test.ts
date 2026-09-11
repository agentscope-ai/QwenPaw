import { describe, expect, it } from "vitest";

import { buildChatPath, getSessionIdFromPath } from "./sessionRoute";

describe("chat session routes", () => {
  it("builds and parses the unified chat route", () => {
    const path = buildChatPath("chat-123");

    expect(path).toBe("/chat/chat-123");
    expect(getSessionIdFromPath(path)).toBe("chat-123");
    expect(buildChatPath()).toBe("/chat");
  });
});
