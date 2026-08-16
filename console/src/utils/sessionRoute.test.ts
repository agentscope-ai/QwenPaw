import { describe, expect, it } from "vitest";

import {
  buildChatPath,
  getAgentIdFromPath,
  getSessionIdFromPath,
  parseChatPath,
  shouldPreserveUrlSessionOnAgentSwitch,
} from "./sessionRoute";

describe("chat session routes", () => {
  it("builds and parses the legacy chat route", () => {
    const path = buildChatPath("chat-123");

    expect(path).toBe("/chat/chat-123");
    expect(getSessionIdFromPath(path)).toBe("chat-123");
    expect(getAgentIdFromPath(path)).toBeUndefined();
    expect(buildChatPath()).toBe("/chat");
  });

  it("builds and parses /chat/:agentId/:sessionId", () => {
    const path = buildChatPath("chat-123", "sales");

    expect(path).toBe("/chat/sales/chat-123");
    expect(parseChatPath(path)).toEqual({
      agentId: "sales",
      sessionId: "chat-123",
    });
    expect(getAgentIdFromPath(path)).toBe("sales");
    expect(getSessionIdFromPath(path)).toBe("chat-123");
  });

  it("encodes and decodes special characters in agent and session ids", () => {
    const path = buildChatPath("sess/a", "agent b");

    expect(path).toBe("/chat/agent%20b/sess%2Fa");
    expect(parseChatPath(path)).toEqual({
      agentId: "agent b",
      sessionId: "sess/a",
    });
  });

  it("treats /chat as empty", () => {
    expect(parseChatPath("/chat")).toEqual({});
    expect(parseChatPath("/chat/")).toEqual({});
  });

  it("preserves the URL session when switching to the agent named in the path", () => {
    expect(
      shouldPreserveUrlSessionOnAgentSwitch("sales", "sales", "sess-1"),
    ).toBe(true);
    expect(
      shouldPreserveUrlSessionOnAgentSwitch("sales", "default", "sess-1"),
    ).toBe(false);
    expect(
      shouldPreserveUrlSessionOnAgentSwitch(undefined, "sales", "sess-1"),
    ).toBe(false);
    expect(
      shouldPreserveUrlSessionOnAgentSwitch("sales", "sales", undefined),
    ).toBe(false);
  });
});
