import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  schedulePatchLastResponseCardUsage,
  wrapChatResponseUsageStream,
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

describe("wrapChatResponseUsageStream", () => {
  it("runs its completion callback after the response stream is consumed", async () => {
    const onComplete = vi.fn();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode("data: {}\n\n"));
        controller.close();
      },
    });
    const wrapped = wrapChatResponseUsageStream(
      new Response(body),
      { current: null },
      undefined,
      onComplete,
    );

    expect(onComplete).not.toHaveBeenCalled();
    await wrapped.text();
    expect(onComplete).toHaveBeenCalledOnce();
  });
});
