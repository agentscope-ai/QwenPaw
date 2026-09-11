/**
 * Issue #6826 — assistant completion time regression tests.
 *
 * Issue #6826: "对话中助手消息结束时间显示异常". When an assistant turn
 * contains long tool calls, the displayed completion time was pinned to
 * ``metadata.timestamp`` (the created_at alias — the first-segment save
 * time), not the moment the reply actually ended. A 2-minute tool turn
 * showed a completion time only seconds after the user sent the message.
 *
 * The backend now stamps ``finished_at`` on REPLY_END and exposes it in
 * message metadata (see ``src/qwenpaw/runtime/executor.py`` and
 * ``src/qwenpaw/app/chats/utils.py``). These tests pin the frontend half:
 * ``buildResponseCard`` must prefer ``metadata.finished_at`` for
 * ``completed_at`` and fall back to ``timestamp`` when it is absent
 * (legacy sessions).
 */
import { describe, it, expect } from "vitest";

// Pure data transforms — no mocks needed; import directly.
import { __test__ } from "../sessionApi";

const { buildResponseCard, parseFinishedAt } = __test__;

function outputMsg(metadata: Record<string, unknown>, seq = 1) {
  return {
    id: `m-${seq}`,
    role: "assistant",
    type: "message",
    sequence_number: seq,
    content: [{ type: "text", text: "ok" }],
    metadata,
  };
}

function cardData(card: ReturnType<typeof buildResponseCard>) {
  const cards = card.cards ?? [];
  return (cards[0] as { data: Record<string, unknown> }).data;
}

describe("parseFinishedAt", () => {
  it("parses a finished_at string to unix seconds", () => {
    const msg = { metadata: { finished_at: "2026-08-12T17:00:00+08:00" } };
    expect(parseFinishedAt(msg)).toBe(
      Math.floor(new Date("2026-08-12T17:00:00+08:00").getTime() / 1000),
    );
  });

  it("returns 0 when finished_at is absent", () => {
    expect(parseFinishedAt({ metadata: {} })).toBe(0);
    expect(parseFinishedAt({ metadata: { finished_at: null } })).toBe(0);
    expect(parseFinishedAt({})).toBe(0);
  });
});

describe("buildResponseCard completed_at (issue #6826)", () => {
  it("prefers finished_at over timestamp for completed_at", () => {
    // created_at (timestamp) pinned at first segment; finished_at ~2min later.
    const created = "2026-08-12T17:00:00+08:00";
    const finished = "2026-08-12T17:02:00+08:00";
    const msgs = [
      outputMsg({ timestamp: created, finished_at: finished }, 1),
      outputMsg({ timestamp: created, finished_at: finished }, 2),
    ];
    const data = cardData(buildResponseCard(msgs as never));
    expect(data.completed_at).toBe(
      Math.floor(new Date(finished).getTime() / 1000),
    );
    // created_at still reflects the first segment.
    expect(data.created_at).toBe(
      Math.floor(new Date(created).getTime() / 1000),
    );
  });

  it("falls back to timestamp when finished_at is absent (legacy)", () => {
    const created = "2026-08-12T17:00:00+08:00";
    const msgs = [outputMsg({ timestamp: created }, 1)];
    const data = cardData(buildResponseCard(msgs as never));
    expect(data.completed_at).toBe(
      Math.floor(new Date(created).getTime() / 1000),
    );
  });

  it("uses the max finished_at across messages in a turn", () => {
    const early = "2026-08-12T17:01:00+08:00";
    const late = "2026-08-12T17:03:00+08:00";
    const msgs = [
      outputMsg({ timestamp: early, finished_at: early }, 1),
      outputMsg({ timestamp: early, finished_at: late }, 2),
    ];
    const data = cardData(buildResponseCard(msgs as never));
    expect(data.completed_at).toBe(Math.floor(new Date(late).getTime() / 1000));
  });
});
