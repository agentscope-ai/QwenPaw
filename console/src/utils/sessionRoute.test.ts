import { describe, expect, it } from "vitest";

import { buildSessionPath, getSessionIdFromPath } from "./sessionRoute";

describe("session mode routes", () => {
  it("preserves the session id across coding and chat routes", () => {
    const sessionId = getSessionIdFromPath("/coding/chat-123");

    expect(buildSessionPath("chat", sessionId)).toBe("/chat/chat-123");
    expect(
      buildSessionPath("coding", getSessionIdFromPath("/chat/chat-123")),
    ).toBe("/coding/chat-123");
  });
});
