import { describe, expect, it } from "vitest";

import {
  analysisErrorMessage,
  createChatStreamState,
  historyToChatMessages,
  reduceChatStreamEvent,
} from "./ChatWorkspace";

describe("QwenPaw Data chat stream reducer", () => {
  it("renders an actionable model credential error", () => {
    const error = Object.assign(new Error("provider rejected the key"), {
      code: "UNAUTHORIZED_MODEL_ACCESS",
    });

    expect(analysisErrorMessage(error)).toBe(
      "The configured language model rejected its credentials. " +
        "Open Settings → Models, update the API key, then retry.",
    );
  });

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
        name: "qwenpaw_data_execute_sql",
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
        name: "qwenpaw_data_execute_sql",
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

  it("rebuilds persisted turns and governed query traces", () => {
    const messages = historyToChatMessages([
      {
        id: "history-user",
        type: "message",
        role: "user",
        content: [
          {
            type: "text",
            delta: false,
            text: "Use QwenPaw-Data source source-1 (Warehouse) for this request unless the user explicitly asks for another source.\n\nShow daily GAAP",
          },
        ],
        metadata: { original_id: "user-1" },
      },
      {
        id: "history-progress",
        type: "message",
        role: "assistant",
        content: [
          {
            type: "text",
            delta: false,
            text: "I will run the governed metric query.",
          },
        ],
        metadata: { original_id: "assistant-1" },
      },
      {
        id: "history-call",
        type: "plugin_call",
        role: "assistant",
        content: [
          {
            type: "data",
            data: {
              call_id: "call-1",
              name: "qwenpaw_data_execute_sql",
              arguments: "{}",
            },
          },
        ],
        metadata: { original_id: "assistant-1" },
      },
      {
        id: "history-output",
        type: "plugin_call_output",
        role: "assistant",
        content: [
          {
            type: "data",
            data: {
              call_id: "call-1",
              name: "qwenpaw_data_execute_sql",
              output: JSON.stringify({
                exec_status: "success",
                columns: ["day", "value"],
                rows: [["2026-03-01", 4.64]],
                total_row_count: 1,
                truncated: false,
              }),
            },
          },
        ],
        metadata: { original_id: "assistant-1" },
      },
      {
        id: "history-final",
        type: "message",
        role: "assistant",
        content: [
          {
            type: "text",
            delta: false,
            text: "The daily average was 4.64.",
          },
        ],
        metadata: { original_id: "assistant-1" },
      },
    ]);

    expect(messages).toEqual([
      expect.objectContaining({
        id: "user:user-1",
        role: "user",
        text: "Show daily GAAP",
      }),
      expect.objectContaining({
        id: "assistant:assistant-1",
        role: "assistant",
        activity: "I will run the governed metric query.",
        text: "The daily average was 4.64.",
        trace: [
          expect.objectContaining({
            id: "call-1",
            label: "Execute governed SQL",
            status: "completed",
            detail: "1 row",
            result: {
              columns: ["day", "value"],
              rows: [["2026-03-01", 4.64]],
              truncated: false,
            },
          }),
        ],
      }),
    ]);
  });
});
