import { describe, expect, it } from "vitest";
import { projectTurnTimeline } from "./steerTimeline";

const msg = (id: string, role: string, ordinal: number, anchor?: string) => ({
  id,
  role,
  content: [{ type: "text", text: id }],
  metadata: {
    after_user_message_id: anchor,
    input_kind: role === "user" ? "steer" : undefined,
    client_message_id: role === "user" ? `c-${id}` : undefined,
    qwenpaw_transcript_position: { turn_id: "t", ordinal },
  },
});

describe("steer timeline ownership", () => {
  it("keeps old output ahead of steer despite final snapshot arrival order", () => {
    const rows = projectTurnTimeline(
      [
        msg("a2", "assistant", 3, "s1"),
        msg("s1", "user", 2),
        msg("tool", "assistant", 1, "u1"),
        msg("a1", "assistant", 0, "u1"),
      ],
      [],
      "t",
    );
    expect(rows.map((r) => r.kind)).toEqual(["assistant", "user", "assistant"]);
    expect(rows[0].messages.map((m) => m.id)).toEqual(["a1", "tool"]);
    expect(rows[2].key).toBe("t:s1");
  });
  it("merges the pending input with committed text without changing its key", () => {
    const receipt = {
      turn_id: "t",
      client_message_id: "c-s1",
      user_message_id: "s1",
      content: [
        { type: "text", text: "s1" },
        { type: "file", file_url: "/media/s1.txt", file_name: "s1.txt" },
      ],
      append_seq: 1,
      revision: 1,
      status: "accepted",
    };
    const before = projectTurnTimeline(
      [msg("a", "assistant", 0, "u1")],
      [receipt],
      "t",
    );
    const after = projectTurnTimeline(
      [msg("a", "assistant", 0, "u1"), msg("s1", "user", 1)],
      [receipt],
      "t",
    );
    expect(before[1].content).toEqual(receipt.content);
    expect(before[1].key).toBe(after[1].key);
    expect(after.filter((r) => r.kind === "user")).toHaveLength(1);
    expect(after[1].status).toBe("applied");
  });
});

it("recovers committed text from receipts and preserves same-batch input order", () => {
  const receipts = [1, 2].map((n) => ({
    turn_id: "t",
    client_message_id: `c-s${n}`,
    user_message_id: `s${n}`,
    content: [{ type: "text", text: `fix ${n}` }],
    append_seq: n,
    revision: 2,
    status: "applied",
    message: msg(`s${n}`, "user", n),
  }));
  const output = [
    msg("a1", "assistant", 0, "u1"),
    msg("a2", "assistant", 3, "s2"),
  ];
  const recovered = projectTurnTimeline(output, receipts, "t");
  expect(recovered.map((r) => r.key)).toEqual(["t:u1", "c-s1", "c-s2", "t:s2"]);
  const full = projectTurnTimeline(
    [...output, ...receipts.map((r) => r.message)],
    receipts,
    "t",
  );
  expect(full.map((r) => r.key)).toEqual(recovered.map((r) => r.key));
  expect(
    recovered.filter((r) => r.kind === "user").map((r) => r.status),
  ).toEqual(["applied", "applied"]);
});

it("keeps an unbound segment anchored while its input body is still missing", () => {
  const output = [
    msg("a1", "assistant", 0, "u1"),
    msg("a2", "assistant", 2, "s1"),
  ];
  const gap = projectTurnTimeline(output, [], "t");
  expect(gap.map((r) => r.kind)).toEqual(["assistant", "user", "assistant"]);
  expect(gap[1].status).toBe("syncing");
  const restored = projectTurnTimeline(
    [...output, msg("s1", "user", 1)],
    [],
    "t",
  );
  expect(restored[2].key).toBe(gap[2].key);
  expect(restored.filter((r) => r.kind === "user")).toHaveLength(1);
});
