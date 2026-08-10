import { describe, expect, it } from "vitest";

import { createChatStreamState, reduceChatStreamEvent } from "./ChatWorkspace";

describe("DataPaw chat stream reducer", () => {
  it("keeps live narration separate from the final assistant answer", () => {
    let state = createChatStreamState();
    state = reduceChatStreamEvent(state, {
      object: "content",
      type: "text",
      delta: true,
      msg_id: "progress-1",
      text: "Checking the governed metric. ",
    });
    state = reduceChatStreamEvent(state, {
      object: "content",
      type: "text",
      delta: true,
      msg_id: "progress-1",
      text: "Running SQL.",
    });
    state = reduceChatStreamEvent(state, {
      object: "content",
      type: "data",
      delta: true,
      status: "in_progress",
      msg_id: "tool-message",
      data: {
        call_id: "call-1",
        name: "datapaw_execute_sql",
        arguments: "",
      },
    });
    state = reduceChatStreamEvent(state, {
      object: "content",
      type: "data",
      delta: false,
      status: "completed",
      msg_id: "tool-output-message",
      data: {
        call_id: "call-1",
        name: "datapaw_execute_sql",
        output: JSON.stringify({
          exec_status: "success",
          columns: ["day", "value"],
          rows: [["2026-03-01", "4.64"]],
          total_row_count: 1,
          truncated: false,
        }),
      },
    });
    state = reduceChatStreamEvent(state, {
      object: "content",
      type: "text",
      delta: true,
      msg_id: "answer-1",
      text: "The daily average was 4.64.",
    });
    state = reduceChatStreamEvent(state, {
      object: "response",
      type: "response",
      status: "completed",
      output: [
        {
          id: "progress-1",
          type: "message",
          role: "assistant",
          content: [
            {
              type: "text",
              delta: false,
              text: "Checking the governed metric. Running SQL.",
            },
          ],
        },
        {
          id: "answer-1",
          type: "message",
          role: "assistant",
          content: [
            {
              type: "text",
              delta: false,
              text: "The daily average was 4.64.",
            },
          ],
        },
      ],
    });

    expect(state.completed).toBe(true);
    expect(state.finalMessageId).toBe("answer-1");
    expect(state.finalText).toBe("The daily average was 4.64.");
    expect(state.textByMessage["progress-1"]).toBe(
      "Checking the governed metric. Running SQL.",
    );
    expect(state.trace).toEqual([
      expect.objectContaining({
        id: "call-1",
        label: "Execute governed SQL",
        status: "completed",
        detail: "1 row",
        result: {
          columns: ["day", "value"],
          rows: [["2026-03-01", "4.64"]],
          truncated: false,
        },
      }),
    ]);
  });

  it("does not duplicate a completed text block after its deltas", () => {
    let state = createChatStreamState();
    state = reduceChatStreamEvent(state, {
      type: "text",
      delta: true,
      msg_id: "answer-1",
      text: "Hello",
    });
    state = reduceChatStreamEvent(state, {
      type: "text",
      delta: false,
      msg_id: "answer-1",
      text: "Hello",
    });

    expect(state.textByMessage["answer-1"]).toBe("Hello");
  });
});
