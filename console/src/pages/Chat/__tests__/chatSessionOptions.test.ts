import { describe, expect, it } from "vitest";
import { buildChatSessionOptions } from "../chatSessionOptions";

describe("buildChatSessionOptions", () => {
  it("keeps the SDK session provider controlled on blank /chat", () => {
    const options = buildChatSessionOptions(undefined);

    expect(
      Object.prototype.hasOwnProperty.call(options, "currentSessionId"),
    ).toBe(true);
    expect(options.currentSessionId).toBeUndefined();
  });

  it("passes the resolved SDK session id when a chat route is active", () => {
    const options = buildChatSessionOptions("chat-uuid");

    expect(options.currentSessionId).toBe("chat-uuid");
  });

  it("uses an Agent-scoped session API for the mounted SDK instance", () => {
    const api = {};
    const options = buildChatSessionOptions("chat-uuid", api);

    expect(options.api).toBe(api);
  });
});
