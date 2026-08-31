import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  readTurnUsageFromResponseCardData,
  schedulePatchLastResponseCardUsage,
} from "./turnUsage";
import { useTurnUsageStore } from "./turnUsageStore";

describe("schedulePatchLastResponseCardUsage", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    useTurnUsageStore.getState().invalidateTurn();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("stops retrying after the originating turn becomes stale", () => {
    const oldTurn = useTurnUsageStore
      .getState()
      .beginTurn("agent-a", "session-a");
    const updateMessage = vi.fn();
    const messages: unknown[] = [];
    const chatRef = {
      current: {
        messages: {
          getMessages: () => messages,
          updateMessage,
        },
      },
    };

    schedulePatchLastResponseCardUsage(
      chatRef as never,
      {
        usage: { model_name: "stale-model", total_tokens: 8 },
        context_usage: null,
      },
      oldTurn,
    );

    useTurnUsageStore.getState().beginTurn("agent-b", "session-b");
    messages.push({ role: "assistant", cards: [] });
    vi.runAllTimers();

    expect(updateMessage).not.toHaveBeenCalled();
  });
});

describe("readTurnUsageFromResponseCardData", () => {
  it("keeps cache usage for a genuine cold miss", () => {
    const snapshot = readTurnUsageFromResponseCardData({
      usage: {
        prompt_tokens: 100,
        completion_tokens: 10,
        total_tokens: 110,
        cache_read_tokens: 0,
        cache_eligible_input_tokens: 100,
        cache_observed: true,
        cache_hit_rate: 0,
        session_cache_read_tokens: 80,
        session_cache_eligible_input_tokens: 200,
        session_cache_observed: true,
        session_cache_hit_rate: 40,
      },
    });

    expect(snapshot?.usage?.cache_observed).toBe(true);
    expect(snapshot?.usage?.cache_hit_rate).toBe(0);
    expect(snapshot?.usage?.session_cache_hit_rate).toBe(40);
  });
});
