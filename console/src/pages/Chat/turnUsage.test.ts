/**
 * Turn usage extraction and patching logic — token/context accounting shown
 * in the chat usage ring. Regression family: streaming usage display (usage
 * arriving late via SSE must still land on the final response card) and
 * context ring denominator recalculation after model switch.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  TURN_USAGE_META_KEY,
  extractTurnUsageFromBackendMetadata,
  extractTurnUsageFromOutputMessages,
  readTurnUsageFromResponseCardData,
  extractLatestSnapshotFromCards,
  patchLastResponseCardUsage,
  patchContextMaxInputLength,
  schedulePatchLastResponseCardUsage,
} from "./turnUsage";
import { useTurnUsageStore } from "./turnUsageStore";

const usage = { provider_id: "p", model_name: "m", total_tokens: 42 };
const ctx = {
  estimated_tokens: 500,
  max_input_length: 1000,
  context_usage_ratio: 50,
};
const fullSnapshot = { usage, context_usage: ctx };

let messageIdCounter = 0;
function cardMessage(data: Record<string, unknown>) {
  return {
    id: `msg-${++messageIdCounter}`,
    role: "assistant" as const,
    cards: [{ code: "AgentScopeRuntimeResponseCard", data }],
  };
}

beforeEach(() => {
  useTurnUsageStore.getState().invalidateTurn();
});

describe("extractTurnUsageFromBackendMetadata", () => {
  it("returns null for non-object metadata", () => {
    expect(extractTurnUsageFromBackendMetadata(null)).toBeNull();
    expect(extractTurnUsageFromBackendMetadata("x")).toBeNull();
  });

  it("reads a top-level turn usage payload", () => {
    expect(
      extractTurnUsageFromBackendMetadata({
        [TURN_USAGE_META_KEY]: { usage, context_usage: ctx },
      }),
    ).toEqual(fullSnapshot);
  });

  it("reads a nested metadata wrapper", () => {
    expect(
      extractTurnUsageFromBackendMetadata({
        metadata: { [TURN_USAGE_META_KEY]: { usage, context_usage: ctx } },
      }),
    ).toEqual(fullSnapshot);
  });

  it("drops zero-token usage payloads", () => {
    expect(
      extractTurnUsageFromBackendMetadata({
        [TURN_USAGE_META_KEY]: {
          usage: { total_tokens: 0 },
          context_usage: { estimated_tokens: 0 },
        },
      }),
    ).toBeNull();
  });

  it("keeps context-only payloads and nulls usage", () => {
    const snap = extractTurnUsageFromBackendMetadata({
      [TURN_USAGE_META_KEY]: { context_usage: ctx },
    });
    expect(snap?.usage).toBeNull();
    expect(snap?.context_usage).toEqual(ctx);
  });

  it("computes totals from prompt+completion when total is missing", () => {
    const snap = extractTurnUsageFromBackendMetadata({
      [TURN_USAGE_META_KEY]: {
        usage: { prompt_tokens: 10, completion_tokens: 5 },
      },
    });
    expect(snap?.usage).toEqual({ prompt_tokens: 10, completion_tokens: 5 });
  });
});

describe("extractTurnUsageFromOutputMessages", () => {
  it("returns null for empty lists", () => {
    expect(extractTurnUsageFromOutputMessages([])).toBeNull();
  });

  it("scans newest message first", () => {
    const newer = {
      metadata: { [TURN_USAGE_META_KEY]: { usage: { total_tokens: 9 } } },
    };
    const older = {
      metadata: { [TURN_USAGE_META_KEY]: { usage: { total_tokens: 1 } } },
    };
    expect(
      extractTurnUsageFromOutputMessages([older, newer])?.usage?.total_tokens,
    ).toBe(9);
  });

  it("falls back to older messages when the newest has none", () => {
    const older = {
      metadata: { [TURN_USAGE_META_KEY]: { usage: { total_tokens: 1 } } },
    };
    expect(
      extractTurnUsageFromOutputMessages([older, {}])?.usage?.total_tokens,
    ).toBe(1);
  });
});

describe("readTurnUsageFromResponseCardData", () => {
  it("returns null for empty or usage-less data", () => {
    expect(readTurnUsageFromResponseCardData(null)).toBeNull();
    expect(readTurnUsageFromResponseCardData({})).toBeNull();
    expect(
      readTurnUsageFromResponseCardData({ usage: { total_tokens: 0 } }),
    ).toBeNull();
  });

  it("reads usage and context from card data", () => {
    expect(
      readTurnUsageFromResponseCardData({ usage, context_usage: ctx }),
    ).toEqual(fullSnapshot);
  });
});

describe("extractLatestSnapshotFromCards", () => {
  it("returns null when no assistant message carries a response card", () => {
    expect(
      extractLatestSnapshotFromCards([
        { id: "m-user", role: "user" as const, cards: [] },
        { id: "m-asst", role: "assistant" as const, cards: [] },
      ]),
    ).toBeNull();
  });

  it("returns the newest assistant card snapshot", () => {
    const oldMsg = cardMessage({ usage: { total_tokens: 1 } });
    const newMsg = cardMessage({
      usage: { total_tokens: 2 },
      context_usage: ctx,
    });
    const snap = extractLatestSnapshotFromCards([oldMsg, newMsg]);
    expect(snap?.usage?.total_tokens).toBe(2);
  });

  it("skips assistant messages without the response card code", () => {
    const withOtherCard = {
      id: "m-other",
      role: "assistant" as const,
      cards: [{ code: "SomeOtherCard", data: { usage: { total_tokens: 3 } } }],
    };
    const withRealCard = cardMessage({ usage: { total_tokens: 7 } });
    expect(
      extractLatestSnapshotFromCards([withRealCard, withOtherCard])?.usage
        ?.total_tokens,
    ).toBe(7);
  });
});

describe("patchLastResponseCardUsage", () => {
  function makeRef(messages: unknown[]) {
    const updateMessage = vi.fn();
    return {
      // Mock ref shape; cast to the SDK ref type expected by the API.
      ref: {
        current: { messages: { getMessages: () => messages, updateMessage } },
      } as never,
      updateMessage,
    };
  }

  it("returns false when the chat ref has no messages api", () => {
    const ref = { current: null };
    expect(patchLastResponseCardUsage(ref, fullSnapshot)).toBe(false);
  });

  it("returns false when there is no assistant response card", () => {
    const { ref } = makeRef([{ role: "assistant", cards: [] }]);
    expect(patchLastResponseCardUsage(ref, fullSnapshot)).toBe(false);
  });

  it("patches the latest assistant card lacking usage", () => {
    const { ref, updateMessage } = makeRef([cardMessage({})]);
    expect(patchLastResponseCardUsage(ref, fullSnapshot)).toBe(true);
    expect(updateMessage).toHaveBeenCalledTimes(1);
    const written = updateMessage.mock.calls[0][0];
    const writtenData = written.cards[0].data;
    expect(writtenData.usage).toEqual(usage);
    expect(writtenData.context_usage).toEqual(ctx);
  });

  it("is a no-op (but true) when usage already matches", () => {
    const { ref, updateMessage } = makeRef([
      cardMessage({ usage, context_usage: ctx }),
    ]);
    expect(patchLastResponseCardUsage(ref, fullSnapshot)).toBe(true);
    expect(updateMessage).not.toHaveBeenCalled();
  });

  it("does not mutate the original message object", () => {
    const original = cardMessage({});
    const { ref } = makeRef([original]);
    patchLastResponseCardUsage(ref, fullSnapshot);
    expect(original.cards[0].data.usage).toBeUndefined();
  });
});

describe("patchContextMaxInputLength", () => {
  function makeRef(messages: unknown[]) {
    const updateMessage = vi.fn();
    return {
      // Mock ref shape; cast to the SDK ref type expected by the API.
      ref: {
        current: { messages: { getMessages: () => messages, updateMessage } },
      } as never,
      updateMessage,
    };
  }

  it("ignores non-positive max input lengths", () => {
    const { ref, updateMessage } = makeRef([
      cardMessage({ usage, context_usage: ctx }),
    ]);
    patchContextMaxInputLength(ref, 0);
    expect(updateMessage).not.toHaveBeenCalled();
  });

  it("recalculates the context ratio for the new denominator", () => {
    const { ref, updateMessage } = makeRef([
      cardMessage({ usage, context_usage: ctx }),
    ]);
    patchContextMaxInputLength(ref, 2000);
    expect(updateMessage).toHaveBeenCalledTimes(1);
    const written = updateMessage.mock.calls[0][0];
    const writtenCtx = written.cards[0].data.context_usage;
    expect(writtenCtx.max_input_length).toBe(2000);
    expect(writtenCtx.context_usage_ratio).toBe(25);
    expect(useTurnUsageStore.getState().snapshot?.context_usage).toEqual(
      writtenCtx,
    );
  });

  it("caps the ratio at 100 percent", () => {
    const { ref, updateMessage } = makeRef([
      cardMessage({ usage, context_usage: ctx }),
    ]);
    patchContextMaxInputLength(ref, 100);
    const writtenCtx =
      updateMessage.mock.calls[0][0].cards[0].data.context_usage;
    expect(writtenCtx.context_usage_ratio).toBe(100);
  });

  it("skips when the card already has the same denominator", () => {
    const { ref, updateMessage } = makeRef([
      cardMessage({ usage, context_usage: ctx }),
    ]);
    patchContextMaxInputLength(ref, 1000);
    expect(updateMessage).not.toHaveBeenCalled();
  });

  it("falls back to updating the store when no card matches", () => {
    const { ref, updateMessage } = makeRef([]);
    useTurnUsageStore.getState().setSnapshot({
      usage,
      context_usage: {
        estimated_tokens: 100,
        max_input_length: 500,
        context_usage_ratio: 20,
      },
    });
    patchContextMaxInputLength(ref, 1000);
    expect(updateMessage).not.toHaveBeenCalled();
    const snap = useTurnUsageStore.getState().snapshot;
    expect(snap?.context_usage?.max_input_length).toBe(1000);
    expect(snap?.context_usage?.context_usage_ratio).toBe(10);
  });
});

describe("turnUsageStore", () => {
  it("beginTurn mints distinct revisions and keeps the projection visible", () => {
    const store = useTurnUsageStore.getState();
    store.setSnapshot(fullSnapshot);
    const t1 = useTurnUsageStore.getState().beginTurn("a1", "s1");
    const t2 = useTurnUsageStore.getState().beginTurn("a1", "s1");
    expect(t1.revision).not.toBe(t2.revision);
    // Upstream #7342: the previous projection stays visible while the next
    // response streams; setSnapshotForTurn replaces it when the turn ends.
    const snap = useTurnUsageStore.getState().snapshot;
    expect(snap).toEqual(fullSnapshot);
  });

  it("setSnapshotForTurn rejects stale turns", () => {
    const t1 = useTurnUsageStore.getState().beginTurn("a1", "s1");
    useTurnUsageStore.getState().beginTurn("a1", "s1");
    expect(
      useTurnUsageStore.getState().setSnapshotForTurn(fullSnapshot, t1),
    ).toBe(false);
  });

  it("setSnapshotForTurn accepts the active turn", () => {
    const t = useTurnUsageStore.getState().beginTurn("a1", "s1");
    expect(
      useTurnUsageStore.getState().setSnapshotForTurn(fullSnapshot, t),
    ).toBe(true);
    expect(useTurnUsageStore.getState().snapshot).toEqual(fullSnapshot);
  });

  it("isTurnActive distinguishes agent/session/revision", () => {
    const t = useTurnUsageStore.getState().beginTurn("a1", "s1");
    const state = useTurnUsageStore.getState();
    expect(state.isTurnActive(t)).toBe(true);
    expect(state.isTurnActive({ ...t, sessionId: "s2" })).toBe(false);
    expect(state.isTurnActive({ ...t, agentId: "a2" })).toBe(false);
    expect(state.isTurnActive({ ...t, revision: t.revision + 1 })).toBe(false);
  });

  it("invalidateTurn clears both the turn and the snapshot", () => {
    const t = useTurnUsageStore.getState().beginTurn("a1", "s1");
    useTurnUsageStore.getState().invalidateTurn();
    const state = useTurnUsageStore.getState();
    expect(state.isTurnActive(t)).toBe(false);
    expect(state.snapshot).toBeNull();
  });

  it("tracks the active max input length", () => {
    useTurnUsageStore.getState().setActiveMaxInputLength(4096);
    expect(useTurnUsageStore.getState().activeMaxInputLength).toBe(4096);
    useTurnUsageStore.getState().setActiveMaxInputLength(null);
    expect(useTurnUsageStore.getState().activeMaxInputLength).toBeNull();
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

// Upstream regression (feat(token-usage) #7342): retry scheduling must stop
// once the originating turn is superseded by a fresh beginTurn on another
// agent/session. Distinct from invalidateTurn() covered in the stream tests.
describe("schedulePatchLastResponseCardUsage (upstream stale-turn guard)", () => {
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
