import type { IAgentScopeRuntimeWebUIMessage } from "@agentscope-ai/chat";
import { describe, expect, it } from "vitest";
import { preserveLiveBubbleIds } from "./chatHistoryRefresh";

type Bubble = IAgentScopeRuntimeWebUIMessage;

function user(id: string, receipt: string, fromHistory = false): Bubble {
  const metadata = { qwenpaw_client_message_id: receipt };
  return {
    id,
    role: "user",
    cards: [
      {
        code: "AgentScopeRuntimeRequestCard",
        data: { input: [{ metadata: fromHistory ? { metadata } : metadata }] },
      },
    ],
  };
}

const assistant = (id: string): Bubble => ({ id, role: "assistant" });

describe("preserveLiveBubbleIds", () => {
  it("matches SDK bubbles to persisted turns by receipt, not order or text", () => {
    const previous = [user("live-user", "receipt"), assistant("live-reply")];
    const next = [
      user("another-user", "unrelated", true),
      assistant("another-reply"),
      user("saved-user", "receipt", true),
      { ...assistant("saved-reply"), msgStatus: "finished" as const },
    ];

    expect(preserveLiveBubbleIds(previous, next)).toEqual([
      ...next.slice(0, 2),
      { ...next[2], id: "live-user" },
      { ...next[3], id: "live-reply" },
    ]);
    expect(next.map(({ id }) => id)).toEqual([
      "another-user",
      "another-reply",
      "saved-user",
      "saved-reply",
    ]);
  });

  it("keeps split history bubbles distinct across multiple refreshes", () => {
    const history = [
      user("saved-part-1", "receipt", true),
      user("saved-part-2", "receipt", true),
      assistant("saved-reply"),
    ];
    const live = [user("live-user", "receipt"), assistant("live-reply")];
    const first = preserveLiveBubbleIds(live, history);
    expect(first.map(({ id }) => id)).toEqual([
      "saved-part-1",
      "live-user",
      "live-reply",
    ]);
    expect(preserveLiveBubbleIds(first, history)).toEqual(first);
    expect(preserveLiveBubbleIds(history, history)).toEqual(history);
  });

  it("does not assign the previous reply id to a newly added reply", () => {
    const previous = [
      user("old-user", "old"),
      assistant("old-reply"),
      user("live-user", "new"),
    ];
    const next = [user("saved-user", "new", true), assistant("saved-reply")];
    expect(preserveLiveBubbleIds(previous, next).map(({ id }) => id)).toEqual([
      "live-user",
      "saved-reply",
    ]);
  });
});
