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

it("keeps each model's pending thinking independent through allocation", () => {
  sessionStorage.clear();
  setPendingThinking("a", "new", { level: "high" }, "p:a");
  setPendingThinking("a", "new", { level: "low" }, "p:b");
  expect(readPendingThinking("a", "new", "p:a")?.level).toBe("high");
  migratePendingThinking("a", "new", "created");
  expect(readPendingThinking("a", "created", "p:a")?.level).toBe("high");
  expect(withPendingThinking({}, "a", "created")).toEqual({
    request_context: { session_thinking: { level: "low" } },
  });
  setPendingThinking("a", "created", null, "p:b");
  expect(readPendingThinking("a", "created", "p:a")?.level).toBe("high");
  expect(readPendingThinking("a", "created", "p:b")).toBeNull();
});
