import { describe, expect, it, vi } from "vitest";

import { resolveStopChatId } from "../chatIdentity";

describe("chat cancel contract", () => {
  it("targets the resolved backend conversation for a temporary UI session", () => {
    const resolveRealId = vi.fn((sessionId: string) =>
      sessionId === "temporary-session" ? "backend-conversation" : null,
    );

    expect(resolveStopChatId("temporary-session", resolveRealId)).toBe(
      "backend-conversation",
    );
    expect(resolveRealId).toHaveBeenCalledWith("temporary-session");
  });

  it("falls back to the existing backend id when no mapping is needed", () => {
    expect(resolveStopChatId("backend-conversation", () => null)).toBe(
      "backend-conversation",
    );
  });
});
