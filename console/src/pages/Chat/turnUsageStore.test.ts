import { beforeEach, describe, expect, it } from "vitest";

import { useTurnUsageStore } from "./turnUsageStore";

describe("turnUsageStore", () => {
  beforeEach(() => {
    useTurnUsageStore.getState().invalidateTurn();
  });

  it("rejects usage from an invalidated turn token", () => {
    const oldTurn = useTurnUsageStore
      .getState()
      .beginTurn("agent-a", "session-a");
    useTurnUsageStore.getState().beginTurn("agent-b", "session-b");

    const accepted = useTurnUsageStore.getState().setSnapshotForTurn(
      {
        usage: {
          provider_id: "openai",
          model_name: "fallback-model",
          total_tokens: 3,
        },
        context_usage: null,
      },
      oldTurn,
    );

    expect(accepted).toBe(false);
    expect(useTurnUsageStore.getState().snapshot).toBeNull();
  });

  it("does not reuse a turn token after invalidation", () => {
    const oldTurn = useTurnUsageStore
      .getState()
      .beginTurn("agent-a", "session-a");
    useTurnUsageStore.getState().invalidateTurn();
    const newTurn = useTurnUsageStore
      .getState()
      .beginTurn("agent-a", "session-a");

    expect(newTurn.revision).toBeGreaterThan(oldTurn.revision);

    const accepted = useTurnUsageStore.getState().setSnapshotForTurn(
      {
        usage: {
          provider_id: "openai",
          model_name: "stale-model",
          total_tokens: 3,
        },
        context_usage: null,
      },
      oldTurn,
    );

    expect(accepted).toBe(false);
    expect(useTurnUsageStore.getState().snapshot).toBeNull();
  });

  it("accepts usage for the active turn token", () => {
    const turn = useTurnUsageStore.getState().beginTurn("agent-a", "session-a");
    const snapshot = {
      usage: { model_name: "active-model", total_tokens: 5 },
      context_usage: null,
    };

    const accepted = useTurnUsageStore
      .getState()
      .setSnapshotForTurn(snapshot, turn);

    expect(accepted).toBe(true);
    expect(useTurnUsageStore.getState().snapshot).toEqual(snapshot);
  });
});
