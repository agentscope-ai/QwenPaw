import { beforeEach, describe, expect, it } from "vitest";
import {
  migratePendingThinking,
  readPendingThinking,
  setPendingThinking,
  withPendingThinking,
} from "./sessionThinkingApi";

describe("pending session thinking", () => {
  beforeEach(() => sessionStorage.clear());
  it("isolates agent/session identities and retains request context", () => {
    setPendingThinking("a", "new", { level: "budget", budget_tokens: 12345 });
    expect(readPendingThinking("b", "new")).toBeNull();
    migratePendingThinking("a", "new", "created");
    expect(readPendingThinking("a", "new")).toBeNull();
    const body = { request_context: { approval_level: "SMART" } };
    expect(withPendingThinking(body, "a", "created")).toEqual({
      request_context: {
        approval_level: "SMART",
        session_thinking: { level: "budget", budget_tokens: 12345 },
      },
    });
    expect(body).toEqual({ request_context: { approval_level: "SMART" } });
    setPendingThinking("a", "created", null);
    expect(withPendingThinking(body, "a", "created")).toBe(body);
  });
});
