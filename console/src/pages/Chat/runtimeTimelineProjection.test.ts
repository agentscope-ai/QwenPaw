import { describe, expect, it } from "vitest";
import { RuntimeTimelineAccumulator } from "./runtimeTimelineProjection";

describe("RuntimeTimelineAccumulator", () => {
  it("accumulates message content deltas and canonical response output", () => {
    const accumulator = new RuntimeTimelineAccumulator();
    accumulator.reset([{ id: "user-a", role: "user", content: "task A" }]);
    accumulator.ingest({
      object: "message",
      id: "assistant-a",
      role: "assistant",
      type: "message",
      content: [],
      metadata: { timeline_group_id: "user-a" },
    });
    accumulator.ingest({
      object: "content",
      msg_id: "assistant-a",
      type: "text",
      text: "hel",
      delta: true,
    });
    accumulator.ingest({
      object: "content",
      msg_id: "assistant-a",
      type: "text",
      text: "lo",
      delta: true,
    });
    accumulator.ingest({
      object: "response",
      status: "completed",
      output: [
        {
          id: "assistant-a",
          role: "assistant",
          type: "message",
          content: [],
          metadata: { timeline_group_id: "user-a" },
        },
      ],
    });

    expect(accumulator.messages()).toHaveLength(2);
    expect(accumulator.messages()[1].content).toEqual([
      expect.objectContaining({ type: "text", text: "hello" }),
    ]);
  });

  it("merges admitted inputs without discarding live output", () => {
    const accumulator = new RuntimeTimelineAccumulator();
    accumulator.reset([{ id: "user-a", role: "user", content: "task A" }]);
    accumulator.ingest({
      object: "message",
      id: "assistant-a",
      role: "assistant",
      content: "working",
    });
    accumulator.mergeBase([{ id: "user-b", role: "user", content: "task B" }]);

    expect(accumulator.messages().map((message) => message.id)).toEqual([
      "user-a",
      "user-b",
      "assistant-a",
    ]);
  });
});
