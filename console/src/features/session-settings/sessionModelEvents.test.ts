import { describe, expect, it } from "vitest";
import { isSessionModelChangedFor } from "./sessionModelEvents";

const scope = { agentId: "agent", sessionId: "session", chatId: "chat" };

describe("isSessionModelChangedFor", () => {
  it("matches an event for the same agent, session and Chat", () => {
    const event = new CustomEvent("session-model-changed", { detail: scope });

    expect(isSessionModelChangedFor(event, scope)).toBe(true);
  });

  it.each(["agentId", "sessionId", "chatId"])(
    "ignores an event with a different %s",
    (field) => {
      const event = new CustomEvent("session-model-changed", {
        detail: { ...scope, [field]: "other" },
      });

      expect(isSessionModelChangedFor(event, scope)).toBe(false);
    },
  );

  it.each([null, undefined])(
    "normalizes a draft event with chatId=%s",
    (chatId) => {
      const event = new CustomEvent("session-model-changed", {
        detail: { ...scope, chatId },
      });

      expect(isSessionModelChangedFor(event, { ...scope, chatId: null })).toBe(
        true,
      );
      expect(
        isSessionModelChangedFor(event, { ...scope, chatId: undefined }),
      ).toBe(true);
      expect(isSessionModelChangedFor(event, scope)).toBe(false);
    },
  );

  it.each(["legacy", "custom"])("accepts an unscoped %s event", (kind) => {
    const event =
      kind === "legacy"
        ? new Event("session-model-changed")
        : new CustomEvent("session-model-changed");

    expect(isSessionModelChangedFor(event, scope)).toBe(true);
  });
});
