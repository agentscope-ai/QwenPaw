import { beforeEach, describe, expect, it } from "vitest";
import {
  getPendingModelOverride,
  migratePendingModelOverride,
  setPendingModelOverride,
  withPendingModelOverride,
} from "./pendingModelOverride";

describe("pendingModelOverride", () => {
  beforeEach(() => sessionStorage.clear());

  it("isolates selections by agent and session", () => {
    setPendingModelOverride("agent-a", "session-a", {
      provider_id: "openai",
      model: "gpt-4o",
    });
    expect(getPendingModelOverride("agent-a", "session-a")).toEqual({
      provider_id: "openai",
      model: "gpt-4o",
    });
    expect(getPendingModelOverride("agent-a", "session-b")).toBeNull();
  });

  it("migrates a new-chat selection to its resolved session", () => {
    setPendingModelOverride("agent-a", "new", {
      provider_id: "anthropic",
      model: "claude-3-5-sonnet",
    });
    migratePendingModelOverride("agent-a", "new", "chat-1");
    expect(getPendingModelOverride("agent-a", "new")).toBeNull();
    expect(getPendingModelOverride("agent-a", "chat-1")?.model).toBe(
      "claude-3-5-sonnet",
    );
  });

  it("adds the selection to the next request body", () => {
    setPendingModelOverride("agent-a", "chat-1", {
      provider_id: "openai",
      model: "gpt-4o",
    });
    const result = withPendingModelOverride(
      { input: [] },
      "agent-a",
      "chat-1",
      "chat-id-1",
    );
    expect(result.requestBody).toEqual({
      input: [],
      model_slot_override: {
        provider_id: "openai",
        model: "gpt-4o",
      },
    });
  });

  it("does not attach a model before the backend chat exists", () => {
    setPendingModelOverride("agent-a", "new", {
      provider_id: "openai",
      model: "gpt-4o",
    });

    expect(
      withPendingModelOverride({ input: [] }, "agent-a", "new", undefined),
    ).toEqual({ requestBody: { input: [] }, modelSlot: null });
  });
});
