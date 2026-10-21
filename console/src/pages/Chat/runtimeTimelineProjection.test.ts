import { describe, expect, it } from "vitest";
import { RuntimeTimelineAccumulator } from "./runtimeTimelineProjection";
import type { Message } from "../../api";
import AgentScopeRuntimeResponseBuilder from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/Response/Builder";
import type { IAgentScopeRuntimeMessage } from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/types";
import { countCollapsedSteps } from "./messageDisplay";

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

describe("delayed Voice history snapshots", () => {
  it("retains a newly committed tail and ongoing output when older history arrives", () => {
    const accumulator = new RuntimeTimelineAccumulator();
    const old = { id: "old", role: "user", content: "previous request" };
    accumulator.reset([old]);
    accumulator.mergeBase([
      { id: "tail", role: "user", content: "last words" },
    ]);
    accumulator.ingest({
      object: "message",
      id: "active",
      role: "assistant",
      content: "still working",
    });
    accumulator.mergeBase([old]);
    expect(accumulator.messages().map((message) => message.id)).toEqual([
      "old",
      "tail",
      "active",
    ]);
  });
});

describe("canonical history reconciliation", () => {
  it("keeps two reasoning and two repeated tool steps stable through history and reload", () => {
    const items: Message[] = ["1", "2"].flatMap((occurrence) => [
      {
        id: `msg_run:reasoning:think-${occurrence}`,
        role: "assistant",
        type: "reasoning",
        content: [{ type: "text", text: "same plan" }],
      },
      {
        id: `msg_run:plugin_call:call-${occurrence}`,
        role: "assistant",
        type: "plugin_call",
        content: [
          {
            type: "data",
            data: {
              call_id: `call-${occurrence}`,
              name: "write_file",
              arguments: "{}",
            },
          },
        ],
      },
      {
        id: `msg_run:plugin_call_output:call-${occurrence}`,
        role: "tool",
        type: "plugin_call_output",
        content: [
          {
            type: "data",
            data: {
              call_id: `call-${occurrence}`,
              name: "write_file",
              output: "ok",
            },
          },
        ],
      },
    ]);
    const accumulator = new RuntimeTimelineAccumulator();
    const steps = () =>
      countCollapsedSteps(
        AgentScopeRuntimeResponseBuilder.mergeToolMessages(
          accumulator.messages() as unknown as IAgentScopeRuntimeMessage[],
        ),
      );
    accumulator.ingest({ object: "response", output: structuredClone(items) });
    expect(steps()).toBe(4);
    accumulator.mergeHistory(
      structuredClone(items),
      accumulator.historyCheckpoint(),
    );
    expect(steps()).toBe(4);
    expect(accumulator.messages()).toHaveLength(6);
    accumulator.reset(items);
    expect(steps()).toBe(4);
  });

  it("continues an item when chunks arrive after history has replaced its live copy", () => {
    const accumulator = new RuntimeTimelineAccumulator();
    const item = {
      id: "msg_run:message:text-1",
      role: "assistant",
      content: [{ type: "text", text: "hel", delta: false }],
    };
    accumulator.ingest({ object: "message", ...structuredClone(item) });
    accumulator.mergeHistory([item], accumulator.historyCheckpoint());
    accumulator.ingest({
      object: "content",
      msg_id: item.id,
      type: "text",
      text: "lo",
      delta: true,
    });
    expect(accumulator.messages()).toHaveLength(1);
    expect(accumulator.messages()[0].content).toEqual([
      expect.objectContaining({ text: "hello" }),
    ]);
    expect(item.content[0].text).toBe("hel");
    accumulator.ingest({
      object: "content",
      msg_id: item.id,
      type: "text",
      text: "hello!",
      delta: false,
    });
    expect(accumulator.messages()[0].content).toEqual([
      expect.objectContaining({ text: "hello!", delta: false }),
    ]);
  });

  it("replaces stale live replies without losing newer tail commits or live output", () => {
    const accumulator = new RuntimeTimelineAccumulator();
    accumulator.ingest({
      object: "message",
      id: "old-reply",
      role: "assistant",
      content: "previous secret",
    });
    accumulator.ingest({
      object: "message",
      id: "active",
      role: "assistant",
      content: "started",
    });
    const checkpoint = accumulator.historyCheckpoint();
    accumulator.mergeBase([{ id: "tail", role: "user", content: "new tail" }]);
    accumulator.ingest({
      object: "message",
      id: "active",
      role: "assistant",
      content: "newer output",
    });
    accumulator.mergeHistory(
      [
        { id: "old-reply", role: "assistant", content: "file created" },
        { id: "active", role: "assistant", content: "started" },
      ],
      checkpoint,
    );
    expect(
      accumulator.messages().find((m) => m.id === "old-reply")?.content,
    ).toBe("file created");
    expect(accumulator.messages().find((m) => m.id === "active")?.content).toBe(
      "newer output",
    );
    expect(accumulator.messages().find((m) => m.id === "tail")?.content).toBe(
      "new tail",
    );
  });

  it("does not roll back a newer history snapshot when an older request finishes late", () => {
    const accumulator = new RuntimeTimelineAccumulator();
    const older = accumulator.historyCheckpoint();
    const newer = accumulator.historyCheckpoint();
    accumulator.mergeHistory(
      [{ id: "reply", role: "assistant", content: "completed" }],
      newer,
    );
    accumulator.mergeHistory(
      [{ id: "reply", role: "assistant", content: "working" }],
      older,
    );
    expect(accumulator.messages()[0].content).toBe("completed");
  });
});
