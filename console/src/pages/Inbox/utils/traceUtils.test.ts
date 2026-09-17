/**
 * Tests for Inbox/utils/traceUtils pure helpers.
 *
 * Covers the public surface of traceUtils: block extraction, collapsibility,
 * trace text extraction, kind normalization, hide/fold decisions, tool field
 * formatting, detail task name normalization, modal title resolution, and the
 * multi-step buildTraceDisplayItems pipeline (tool_call/tool_output pairing,
 * response_completed filtering, multi-block splitting).
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import type { PushMessage } from "../types";
import {
  buildContentFallbackTrace,
  getPrimaryTraceBlock,
  isCollapsibleTraceEvent,
  extractTraceText,
  normalizeTraceKind,
  shouldHideTraceEvent,
  getTraceFoldTitle,
  getToolFieldText,
  formatToolInput,
  formatToolBlockContent,
  normalizeDetailTaskName,
  getDetailModalTitle,
  buildTraceDisplayItems,
} from "./traceUtils";

const makeMessage = (overrides: Partial<PushMessage> = {}): PushMessage =>
  ({
    id: "m1",
    channelType: "wechat",
    channelName: "wechat",
    title: "hello",
    content: "hi",
    sender: { userId: "u1", username: "alice" },
    createdAt: new Date("2024-01-01T00:00:00Z"),
    read: false,
    ...overrides,
  }) as unknown as PushMessage;

describe("buildContentFallbackTrace", () => {
  it("returns assistant text event when content exists", () => {
    const msg = makeMessage({ content: "ping" });
    const trace = buildContentFallbackTrace(msg);
    expect(trace.events).toHaveLength(1);
    const evt = trace.events[0];
    expect(evt.at).toBe(msg.createdAt.getTime() / 1000);
    expect(evt.event.role).toBe("assistant");
    const block = (
      evt.event as { content: Array<{ type: string; text: string }> }
    ).content[0];
    expect(block.type).toBe("text");
    expect(block.text).toBe("ping");
  });

  it("returns empty events when content is empty", () => {
    const msg = makeMessage({ content: "" });
    const trace = buildContentFallbackTrace(msg);
    expect(trace.events).toEqual([]);
  });
});

describe("getPrimaryTraceBlock", () => {
  it("returns first element for non-empty array of objects", () => {
    const block = { type: "text", text: "a" };
    expect(getPrimaryTraceBlock({ content: [block] })).toStrictEqual(block);
  });

  it("returns null for empty array", () => {
    expect(getPrimaryTraceBlock({ content: [] })).toBeNull();
  });

  it("returns null when content missing", () => {
    expect(getPrimaryTraceBlock({})).toBeNull();
  });

  it("returns null when first element is not an object", () => {
    expect(getPrimaryTraceBlock({ content: ["str"] })).toBeNull();
  });
});

describe("isCollapsibleTraceEvent", () => {
  it("returns true when kind contains thinking", () => {
    expect(isCollapsibleTraceEvent("thinking_started", { content: [] })).toBe(
      true,
    );
  });

  it("returns true when kind contains tool", () => {
    expect(isCollapsibleTraceEvent("tool_call", { content: [] })).toBe(true);
  });

  it("returns true when block.type is thinking", () => {
    expect(
      isCollapsibleTraceEvent("other", { content: [{ type: "thinking" }] }),
    ).toBe(true);
  });

  it("returns true when block.type is tool_use", () => {
    expect(
      isCollapsibleTraceEvent("other", { content: [{ type: "tool_use" }] }),
    ).toBe(true);
  });

  it("returns true when block.type is tool_result", () => {
    expect(
      isCollapsibleTraceEvent("other", { content: [{ type: "tool_result" }] }),
    ).toBe(true);
  });

  it("returns false for plain text block", () => {
    expect(
      isCollapsibleTraceEvent("other", {
        content: [{ type: "text", text: "x" }],
      }),
    ).toBe(false);
  });
});

describe("extractTraceText", () => {
  it("extracts thinking field from thinking block", () => {
    expect(
      extractTraceText({
        content: [{ type: "thinking", thinking: "  hmm  " }],
      }),
    ).toBe("hmm");
  });

  it("extracts text field from text block", () => {
    expect(
      extractTraceText({ content: [{ type: "text", text: "hello" }] }),
    ).toBe("hello");
  });

  it("joins tool_result output array text with newline", () => {
    const event = {
      content: [
        {
          type: "tool_result",
          output: [{ text: "line1" }, { text: "line2" }],
        },
      ],
    };
    expect(extractTraceText(event)).toBe("line1\nline2");
  });

  it("extracts raw_input from tool_use block", () => {
    expect(
      extractTraceText({
        content: [{ type: "tool_use", raw_input: '{"a":1}' }],
      }),
    ).toBe('{"a":1}');
  });

  it("falls back to input when raw_input missing on tool_use", () => {
    expect(
      extractTraceText({ content: [{ type: "tool_use", input: "in" }] }),
    ).toBe("in");
  });

  it("returns empty string when block missing", () => {
    expect(extractTraceText({})).toBe("");
  });
});

describe("normalizeTraceKind", () => {
  it("returns response_completed for response_completed type", () => {
    expect(normalizeTraceKind({ type: "response_completed" })).toBe(
      "response_completed",
    );
  });

  it("normalizes thinking block", () => {
    expect(normalizeTraceKind({ content: [{ type: "thinking" }] })).toBe(
      "thinking",
    );
  });

  it("normalizes tool_use block to tool_call", () => {
    expect(normalizeTraceKind({ content: [{ type: "tool_use" }] })).toBe(
      "tool_call",
    );
  });

  it("normalizes tool_call block to tool_call", () => {
    expect(normalizeTraceKind({ content: [{ type: "tool_call" }] })).toBe(
      "tool_call",
    );
  });

  it("normalizes tool_result block to tool_output", () => {
    expect(normalizeTraceKind({ content: [{ type: "tool_result" }] })).toBe(
      "tool_output",
    );
  });

  it("normalizes text block to push_preview", () => {
    expect(normalizeTraceKind({ content: [{ type: "text" }] })).toBe(
      "push_preview",
    );
  });

  it("falls back to event for unknown block types", () => {
    expect(normalizeTraceKind({ content: [{ type: "weird" }] })).toBe("event");
  });
});

describe("shouldHideTraceEvent", () => {
  it("hides response_completed", () => {
    expect(shouldHideTraceEvent("response_completed", {})).toBe(true);
  });

  it("hides events with no trace text and not collapsible", () => {
    // empty text block: no text content, text is not collapsible
    expect(shouldHideTraceEvent("event", { content: [{ type: "text" }] })).toBe(
      true,
    );
  });

  it("shows events with trace text", () => {
    expect(
      shouldHideTraceEvent("event", {
        content: [{ type: "text", text: "hi" }],
      }),
    ).toBe(false);
  });

  it("shows collapsible events even without text", () => {
    expect(
      shouldHideTraceEvent("event", { content: [{ type: "thinking" }] }),
    ).toBe(false);
  });
});

describe("getTraceFoldTitle", () => {
  it("returns Thinking for thinking kind", () => {
    expect(getTraceFoldTitle("thinking_done", {})).toBe("Thinking");
  });

  it("returns block name for tool kind with name", () => {
    expect(
      getTraceFoldTitle("tool_call", {
        content: [{ type: "tool_use", name: "search" }],
      }),
    ).toBe("search");
  });

  it("returns Tool for tool kind without name", () => {
    expect(
      getTraceFoldTitle("tool_call", { content: [{ type: "tool_use" }] }),
    ).toBe("Tool");
  });

  it("returns Details for other kinds", () => {
    expect(getTraceFoldTitle("other", {})).toBe("Details");
  });
});

describe("getToolFieldText", () => {
  it("returns raw_input for tool_input on tool_use", () => {
    expect(
      getToolFieldText(
        { content: [{ type: "tool_use", raw_input: '{"a":1}' }] },
        "tool_input",
      ),
    ).toBe('{"a":1}');
  });

  it("returns input string for tool_input when raw_input missing", () => {
    expect(
      getToolFieldText(
        { content: [{ type: "tool_use", input: "raw" }] },
        "tool_input",
      ),
    ).toBe("raw");
  });

  it("stringifies non-string input for tool_input", () => {
    expect(
      getToolFieldText(
        { content: [{ type: "tool_use", input: { a: 1 } }] },
        "tool_input",
      ),
    ).toBe(JSON.stringify({ a: 1 }, null, 2));
  });

  it("returns JSON.stringify of output for tool_output on tool_result", () => {
    const output = [{ text: "x" }];
    expect(
      getToolFieldText(
        { content: [{ type: "tool_result", output }] },
        "tool_output",
      ),
    ).toBe(JSON.stringify(output, null, 2));
  });

  it("returns empty string when field mismatched", () => {
    expect(
      getToolFieldText(
        { content: [{ type: "text", text: "x" }] },
        "tool_input",
      ),
    ).toBe("");
  });

  it("returns empty string when block missing", () => {
    expect(getToolFieldText({}, "tool_input")).toBe("");
  });
});

describe("formatToolInput", () => {
  it("returns {} for empty/whitespace", () => {
    expect(formatToolInput("   ")).toBe("{}");
    expect(formatToolInput("")).toBe("{}");
  });

  it("returns text as-is for non-empty", () => {
    expect(formatToolInput('{"a":1}')).toBe('{"a":1}');
  });
});

describe("formatToolBlockContent", () => {
  it("returns empty string for whitespace", () => {
    expect(formatToolBlockContent("   ")).toBe("");
  });

  it("formats valid JSON", () => {
    expect(formatToolBlockContent('{"b":2,"a":1}')).toBe(
      JSON.stringify({ b: 2, a: 1 }, null, 2),
    );
  });

  it("returns text as-is for invalid JSON", () => {
    expect(formatToolBlockContent("not json")).toBe("not json");
  });
});

describe("normalizeDetailTaskName", () => {
  it("strips cron result: prefix", () => {
    expect(normalizeDetailTaskName("cron result: My Job")).toBe("My Job");
  });

  it("strips heartbeat result: prefix", () => {
    expect(normalizeDetailTaskName("heartbeat result: X")).toBe("X");
  });

  it("strips Chinese 定时任务结果: prefix", () => {
    expect(normalizeDetailTaskName("定时任务结果: 我的工作")).toBe("我的工作");
  });

  it("strips Chinese 心跳结果: prefix", () => {
    expect(normalizeDetailTaskName("心跳结果: 心跳")).toBe("心跳");
  });

  it("returns dash for empty title", () => {
    expect(normalizeDetailTaskName("")).toBe("-");
  });

  it("returns title as-is when no prefix matches", () => {
    expect(normalizeDetailTaskName("plain title")).toBe("plain title");
  });
});

describe("getDetailModalTitle", () => {
  const t = vi.fn((key: string, opts?: Record<string, unknown>) =>
    opts ? `${key}:${JSON.stringify(opts)}` : key,
  );

  beforeEach(() => {
    t.mockClear();
  });

  it("returns messageDetailTitle for null message", () => {
    expect(getDetailModalTitle(null, t)).toBe("inbox.messageDetailTitle");
    expect(t).toHaveBeenCalledWith("inbox.messageDetailTitle");
  });

  it("returns detailCronTitle with normalized name for cron source", () => {
    const msg = makeMessage({
      title: "cron result: Job A",
      metadata: { sourceType: "cron" },
    });
    expect(getDetailModalTitle(msg, t)).toBe(
      `inbox.detailCronTitle:${JSON.stringify({ name: "Job A" })}`,
    );
  });

  it("returns detailHeartbeatTitle for heartbeat source", () => {
    const msg = makeMessage({ metadata: { sourceType: "heartbeat" } });
    expect(getDetailModalTitle(msg, t)).toBe("inbox.detailHeartbeatTitle");
  });

  it("returns title for other sources", () => {
    const msg = makeMessage({
      title: "Hey",
      metadata: { sourceType: "wechat" },
    });
    expect(getDetailModalTitle(msg, t)).toBe("Hey");
  });

  it("falls back to messageDetailTitle when title empty and unknown source", () => {
    const msg = makeMessage({ title: "", metadata: { sourceType: "wechat" } });
    expect(getDetailModalTitle(msg, t)).toBe("inbox.messageDetailTitle");
  });
});

describe("buildTraceDisplayItems", () => {
  it("returns empty array for empty input", () => {
    expect(buildTraceDisplayItems([])).toEqual([]);
  });

  it("filters out response_completed events", () => {
    const result = buildTraceDisplayItems([
      {
        at: 1,
        event: {
          type: "response_completed",
          content: [{ type: "text", text: "x" }],
        },
      },
    ]);
    expect(result).toEqual([]);
  });

  it("pairs tool_call with tool_output by tool_name", () => {
    const result = buildTraceDisplayItems([
      {
        at: 1,
        event: {
          tool_name: "search",
          content: [{ type: "tool_use", name: "search", raw_input: "q" }],
        },
      },
      {
        at: 2,
        event: {
          tool_name: "search",
          content: [{ type: "tool_result", output: [{ text: "r" }] }],
        },
      },
    ]);
    expect(result).toHaveLength(1);
    const item = result[0];
    expect(item.renderKind).toBe("tool_pair");
    expect(item.eventType).toBe("tool_call");
    expect(item.toolInput).toBe("q");
    expect(item.toolOutput).toContain("r");
    expect(item.collapsible).toBe(true);
  });

  it("keeps unpaired tool_call when no tool_output follows", () => {
    const result = buildTraceDisplayItems([
      {
        at: 1,
        event: {
          tool_name: "search",
          content: [{ type: "tool_use", name: "search", raw_input: "q" }],
        },
      },
    ]);
    expect(result).toHaveLength(1);
    expect(result[0].renderKind).toBe("tool_pair");
    expect(result[0].toolInput).toBe("q");
    expect(result[0].toolOutput).toBeUndefined();
  });

  it("keeps standalone tool_output as tool_pair", () => {
    const result = buildTraceDisplayItems([
      {
        at: 1,
        event: {
          content: [{ type: "tool_result", output: [{ text: "x" }] }],
        },
      },
    ]);
    expect(result).toHaveLength(1);
    expect(result[0].renderKind).toBe("tool_pair");
    expect(result[0].eventType).toBe("tool_output");
  });

  it("splits multi-block content into separate items", () => {
    const result = buildTraceDisplayItems([
      {
        at: 1,
        event: {
          content: [
            { type: "text", text: "first" },
            { type: "thinking", thinking: "plan" },
          ],
        },
      },
    ]);
    expect(result).toHaveLength(2);
    expect(result[0].eventType).toBe("push_preview");
    expect(result[0].traceText).toBe("first");
    expect(result[1].eventType).toBe("thinking");
    expect(result[1].traceText).toBe("plan");
    expect(result[1].collapsible).toBe(true);
  });

  it("normalizes single-block event as normal push_preview", () => {
    const result = buildTraceDisplayItems([
      {
        at: 1,
        event: { content: [{ type: "text", text: "hi" }] },
      },
    ]);
    expect(result).toHaveLength(1);
    expect(result[0].renderKind).toBe("normal");
    expect(result[0].eventType).toBe("push_preview");
    expect(result[0].traceText).toBe("hi");
  });
});
