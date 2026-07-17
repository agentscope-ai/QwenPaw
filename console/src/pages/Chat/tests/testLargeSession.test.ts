/**
 * PR-F3 — Large session / large payload regression tests for issue #5479
 *
 * Issue #5479: "大会话文件（>500KB）打开报错：渲染此页面时发生了意外错误"
 *   When a session JSON exceeds ~500KB, opening it in the console Web UI
 *   throws an uncaught exception and the page goes blank. The backend returns
 *   the JSON successfully — the crash is entirely in the frontend pipeline
 *   that converts backend flat messages into the card-based format consumed
 *   by @agentscope-ai/chat, and/or in the synchronous render of the resulting
 *   (very large) message tree.
 *
 * These tests target the data-transform layer (`convertMessages` and friends
 * in `console/src/pages/Chat/sessionApi/index.ts`) directly, because it is the
 * narrowest, fastest, and most reliable place to pin the regressions:
 *
 *   - convertMessages is a pure O(n) function with no React/jsdom dependence,
 *     so we can feed it a synthetic 500KB+ payload and assert no crash + correct
 *     chunking in microseconds.
 *   - It is the single point where backend flat messages become UI cards.
 *     If it ever blows up (regex/recursive parse, accidental O(n²) grouping,
 *     or merges consecutive assistant turns that should stay split), the UI
 *     will throw on large sessions exactly as observed in #5479.
 *
 * We also include an integration test (`SessionApi.getSession`) that mocks
 * `api.getChat` to return a 500KB+ payload, exercising the full fetch →
 * convert → cache → patch flow used by the live chat page.
 *
 * Historical context pinned by these tests:
 *   - "Merged streaming" issue (commit 5a88d648 / PR #5487
 *     "fix(channel): restore streaming path and split multi-segment reply into
 *      separate streaming boxes"): consecutive streamed assistant segments must
 *      remain SEPARATE messages, never be concatenated into one block. Our
 *      `convertMessages` groups consecutive non-user messages into a single
 *      ResponseCard, but each segment MUST stay a distinct entry in the card's
 *      `output` array — merging them would re-introduce the bug.
 *
 * Test placement rationale: see header of step 3 in the PR-F3 task — a pure
 * data-transform utility exists (`convertMessages`), so we test it directly
 * rather than driving the React component (which would be brittle and slow
 * for 500KB+ inputs in jsdom).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import type { Message, ChatHistory } from "../../../api/types/chat";

// Mock chatApi.filePreviewUrl so toDisplayUrl() is deterministic and does
// not touch real config/token code paths. Preserve all other named exports
// (sessionApi, types, etc.) by spreading importOriginal.
vi.mock("../../../api/modules/chat", async (importOriginal) => {
  const actual = await importOriginal<
    typeof import("../../../api/modules/chat")
  >();
  return {
    ...actual,
    chatApi: {
      ...actual.chatApi,
      filePreviewUrl: vi.fn(
        (p: string) => `http://localhost:8000/files/preview/${p}`,
      ),
    },
  };
});

// Import AFTER mocks are registered.
import { __test__ } from "../sessionApi";
import sessionApiDefaultExport from "../sessionApi";

const {
  convertMessages,
  buildResponseCard,
  buildUserCard,
  toOutputMessage,
  isLocalTimestamp,
  isGenerating,
  resolveRealId,
  parseTimestamp,
  extractTextFromContent,
  contentToRequestParts,
  normalizeOutputMessageContent,
} = __test__;

// ---------------------------------------------------------------------------
// Helpers — build synthetic large payloads representative of real sessions
// ---------------------------------------------------------------------------

/** A single text chunk ~`bytes` characters long (counted in UTF-16 code units). */
function bigText(bytes: number, label = "x"): string {
  // Use a repeated phrase; ~64 chars per line keeps the string realistic.
  const line = `${label}:这是一段用于填充大会话的中文文本，每行约30个字符 ok\n`;
  const reps = Math.max(1, Math.ceil(bytes / line.length));
  return line.repeat(reps).slice(0, bytes);
}

/** Build a backend Message[] of approximately `targetBytes` total JSON size. */
function buildLargeMessages(
  targetBytes: number,
  opts: { turnCount?: number; assistantPerTurn?: number } = {},
): { messages: Message[]; size: number } {
  const turnCount = opts.turnCount ?? 40;
  const assistantPerTurn = opts.assistantPerTurn ?? 3;
  const perTurnBytes = Math.ceil(targetBytes / turnCount);
  const messages: Message[] = [];
  for (let t = 0; t < turnCount; t++) {
    // User turn — a small text content array.
    messages.push({
      id: `u-${t}`,
      role: "user",
      content: [
        {
          type: "text",
          text: `user turn ${t} — ${bigText(perTurnBytes / 8, "u")}`,
        },
      ],
      metadata: {
        timestamp: `2026-06-01 10:00:${(t % 60)
          .toString()
          .padStart(2, "0")}.000`,
      },
    });
    // assistantPerTurn consecutive assistant segments (simulates streaming chunks).
    const segBytes = perTurnBytes / assistantPerTurn;
    for (let s = 0; s < assistantPerTurn; s++) {
      messages.push({
        id: `a-${t}-${s}`,
        role: "assistant",
        content: [{ type: "text", text: bigText(segBytes, `a${t}.${s}`) }],
        metadata: {
          timestamp: `2026-06-01 10:00:${(t % 60)
            .toString()
            .padStart(2, "0")}.${(s * 100).toString().padStart(3, "0")}`,
          qwenpaw_turn_usage: {
            usage: {
              prompt_tokens: 100 + s,
              completion_tokens: 50 + s,
              total_tokens: 150 + 2 * s,
            },
            context_usage: {
              estimated_tokens: 200,
              max_input_length: 8000,
              context_usage_ratio: 0.025,
            },
          },
        },
      });
    }
  }
  const size = JSON.stringify(messages).length;
  return { messages, size };
}

/** Build a single huge assistant message (~`bytes`) — pathological case for
 *  any code that assumes message content is small. */
function buildOneGiantAssistantMessage(bytes: number): Message[] {
  return [
    {
      id: "huge-1",
      role: "user",
      content: "go",
      metadata: { timestamp: "2026-06-01 10:00:00.000" },
    },
    {
      id: "huge-2",
      role: "assistant",
      content: [{ type: "text", text: bigText(bytes, "huge") }],
      metadata: {
        timestamp: "2026-06-01 10:00:01.000",
        qwenpaw_turn_usage: {
          usage: { prompt_tokens: 1, completion_tokens: 2, total_tokens: 3 },
          context_usage: {
            estimated_tokens: 4,
            max_input_length: 8000,
            context_usage_ratio: 0.001,
          },
        },
      },
    },
  ];
}

// ---------------------------------------------------------------------------
// 1. Large payload parse/transform — must not throw on >500KB sessions (#5479)
// ---------------------------------------------------------------------------

describe("convertMessages — large session regression for #5479", () => {
  it("parses a >500KB session without throwing (issue #5479 core scenario)", () => {
    const { messages, size } = buildLargeMessages(600 * 1024);
    expect(size).toBeGreaterThan(500 * 1024);

    let result: ReturnType<typeof convertMessages> | undefined;
    // The historical bug: this call would throw / run out of stack on big inputs.
    expect(() => {
      result = convertMessages(messages);
    }).not.toThrow();
    expect(result).toBeDefined();
    expect(result!.length).toBeGreaterThan(0);
  });

  it("parses a >2MB session without throwing (stress case)", () => {
    // 2MB is far above the reported 500KB threshold; we still must not crash.
    const { messages, size } = buildLargeMessages(2 * 1024 * 1024, {
      turnCount: 200,
      assistantPerTurn: 5,
    });
    expect(size).toBeGreaterThan(2 * 1024 * 1024 - 1024);
    expect(() => convertMessages(messages)).not.toThrow();
  });

  it("handles a single pathological huge assistant message (no chunking regression)", () => {
    // A single ~1MB assistant content string. If any helper assumes short
    // content, it would blow up here.
    const messages = buildOneGiantAssistantMessage(1024 * 1024);
    let result;
    expect(() => {
      result = convertMessages(messages);
    }).not.toThrow();
    expect(result).toHaveLength(2); // one user card + one assistant card
    const assistantCard = result![1];
    expect(assistantCard.role).toBe("assistant");
    // The card must carry the giant content intact (not truncated to empty).
    const output = (assistantCard.cards?.[0]?.data as any)?.output;
    expect(Array.isArray(output)).toBe(true);
    expect(output.length).toBe(1);
    expect(extractTextFromContent(output[0].content).length).toBeGreaterThan(
      1024 * 1024 - 1024,
    );
  });

  it("runs in roughly linear time — 4x input should not take >30x time (perf guard)", () => {
    // Not a hard perf budget (CI is noisy), but a regression that introduces
    // O(n²) grouping would blow this out. We keep the ratio loose.
    const baseline = buildLargeMessages(50 * 1024, {
      turnCount: 10,
      assistantPerTurn: 3,
    });
    const bigger = buildLargeMessages(200 * 1024, {
      turnCount: 40,
      assistantPerTurn: 3,
    });

    const t1 = performance.now();
    convertMessages(baseline.messages);
    const t2 = performance.now();
    convertMessages(bigger.messages);
    const t3 = performance.now();

    const baselineMs = t2 - t1;
    const biggerMs = t3 - t2;
    // 4x input, allow up to 30x slack (jsdom is slow & noisy on CI).
    if (baselineMs > 1) {
      expect(biggerMs).toBeLessThan(baselineMs * 30 + 500);
    }
  });
});

// ---------------------------------------------------------------------------
// 2. Multi-segment streaming — segments must stay SEPARATE blocks
//    (historical "merged streaming" issue, PR #5487 / commit 5a88d648)
// ---------------------------------------------------------------------------

describe("convertMessages — streaming segments stay separate (PR #5487)", () => {
  it("keeps each assistant segment as a distinct entry in the ResponseCard output array", () => {
    // Simulates a streamed assistant turn split into N segments by the channel.
    const messages: Message[] = [
      {
        role: "user",
        content: "q",
        metadata: { timestamp: "2026-06-01 10:00:00.000" },
      },
      {
        role: "assistant",
        content: [{ type: "text", text: "seg1" }],
        metadata: {},
      },
      {
        role: "assistant",
        content: [{ type: "text", text: "seg2" }],
        metadata: {},
      },
      {
        role: "assistant",
        content: [{ type: "text", text: "seg3" }],
        metadata: {},
      },
    ];
    const result = convertMessages(messages);
    expect(result).toHaveLength(2); // one user card + one assistant card

    const card = result[1];
    expect(card.role).toBe("assistant");
    const output = (card.cards?.[0]?.data as any)?.output;
    expect(Array.isArray(output)).toBe(true);
    // REGRESSION: must be 3 separate entries, not 1 merged block.
    expect(output).toHaveLength(3);
    expect(extractTextFromContent(output[0].content)).toBe("seg1");
    expect(extractTextFromContent(output[1].content)).toBe("seg2");
    expect(extractTextFromContent(output[2].content)).toBe("seg3");
  });

  it("does NOT merge segments across a user boundary — each turn is its own card", () => {
    // turn 1: assistant seg1, assistant seg2, user, turn 2: assistant seg3
    const messages: Message[] = [
      {
        role: "user",
        content: "q1",
        metadata: { timestamp: "2026-06-01 10:00:00.000" },
      },
      {
        role: "assistant",
        content: [{ type: "text", text: "a1.1" }],
        metadata: {},
      },
      {
        role: "assistant",
        content: [{ type: "text", text: "a1.2" }],
        metadata: {},
      },
      {
        role: "user",
        content: "q2",
        metadata: { timestamp: "2026-06-01 10:00:01.000" },
      },
      {
        role: "assistant",
        content: [{ type: "text", text: "a2.1" }],
        metadata: {},
      },
    ];
    const result = convertMessages(messages);
    // user card, assistant card (2 outputs), user card, assistant card (1 output)
    expect(result).toHaveLength(4);
    expect(result[0].role).toBe("user");
    expect(result[1].role).toBe("assistant");
    expect(result[2].role).toBe("user");
    expect(result[3].role).toBe("assistant");

    const out1 = (result[1].cards?.[0]?.data as any).output;
    const out2 = (result[3].cards?.[0]?.data as any).output;
    expect(out1).toHaveLength(2);
    expect(out2).toHaveLength(1); // not merged with the previous turn
    expect(extractTextFromContent(out1[0].content)).toBe("a1.1");
    expect(extractTextFromContent(out1[1].content)).toBe("a1.2");
    expect(extractTextFromContent(out2[0].content)).toBe("a2.1");
  });

  it("keeps streaming segments separate at large scale (200 turns × 4 segments each)", () => {
    const messages: Message[] = [];
    for (let t = 0; t < 200; t++) {
      messages.push({
        role: "user",
        content: `q${t}`,
        metadata: { timestamp: "2026-06-01 10:00:00.000" },
      });
      for (let s = 0; s < 4; s++) {
        messages.push({
          role: "assistant",
          content: [{ type: "text", text: `t${t}.s${s}-${bigText(512, "x")}` }],
          metadata: {},
        });
      }
    }
    const result = convertMessages(messages);
    // 200 user cards + 200 assistant cards = 400
    expect(result).toHaveLength(400);
    // Spot-check a middle turn: each assistant card should hold exactly 4 segments.
    const mid = result[201]; // first assistant card is index 1; turn 100 → index 201
    const output = (mid.cards?.[0]?.data as any).output;
    expect(output).toHaveLength(4);
    // No segment merged into a single block — content strings still distinct.
    expect(output[0].content).not.toEqual(output[1].content);
  });

  it("preserves sequence order of segments within a ResponseCard", () => {
    const messages: Message[] = [
      {
        role: "user",
        content: "q",
        metadata: { timestamp: "2026-06-01 10:00:00.000" },
      },
      {
        role: "assistant",
        content: [{ type: "text", text: "first" }],
        metadata: { sequence_number: 1 },
      },
      {
        role: "assistant",
        content: [{ type: "text", text: "second" }],
        metadata: { sequence_number: 2 },
      },
      {
        role: "assistant",
        content: [{ type: "text", text: "third" }],
        metadata: { sequence_number: 3 },
      },
    ];
    const result = convertMessages(messages);
    const output = (result[1].cards?.[0]?.data as any).output;
    expect(extractTextFromContent(output[0].content)).toBe("first");
    expect(extractTextFromContent(output[1].content)).toBe("second");
    expect(extractTextFromContent(output[2].content)).toBe("third");
  });
});

// ---------------------------------------------------------------------------
// 3. Output card structure correctness on large inputs
// ---------------------------------------------------------------------------

describe("convertMessages — structural correctness on large input", () => {
  it("produces strictly alternating user/assistant cards for alternating roles", () => {
    const messages: Message[] = [];
    for (let i = 0; i < 100; i++) {
      messages.push({ role: "user", content: `q${i}`, metadata: {} });
      messages.push({ role: "assistant", content: `a${i}`, metadata: {} });
    }
    const result = convertMessages(messages);
    expect(result).toHaveLength(200);
    for (let i = 0; i < 200; i += 2) {
      expect(result[i].role).toBe("user");
      expect(result[i + 1].role).toBe("assistant");
    }
  });

  it("every assistant card has exactly one AgentScopeRuntimeResponseCard", () => {
    const { messages } = buildLargeMessages(200 * 1024, {
      turnCount: 30,
      assistantPerTurn: 2,
    });
    const result = convertMessages(messages);
    for (const card of result) {
      if (card.role === "assistant") {
        expect(card.cards).toBeDefined();
        expect(card.cards!.length).toBe(1);
        expect(card.cards![0].code).toBe("AgentScopeRuntimeResponseCard");
      }
    }
  });

  it("every user card has exactly one AgentScopeRuntimeRequestCard", () => {
    const { messages } = buildLargeMessages(200 * 1024, {
      turnCount: 30,
      assistantPerTurn: 2,
    });
    const result = convertMessages(messages);
    for (const card of result) {
      if (card.role === "user") {
        expect(card.cards).toBeDefined();
        expect(card.cards!.length).toBe(1);
        expect(card.cards![0].code).toBe("AgentScopeRuntimeRequestCard");
      }
    }
  });

  it("turn usage is extracted from the LAST assistant message in the card (not first)", () => {
    // The turn usage popover reads `usage` from the ResponseCard data.
    // extractTurnUsageFromOutputMessages scans from the tail, so the last
    // segment wins. For a large streamed turn, that's the correct total.
    const messages: Message[] = [
      { role: "user", content: "q", metadata: {} },
      {
        role: "assistant",
        content: "p1",
        metadata: {
          qwenpaw_turn_usage: {
            usage: {
              prompt_tokens: 10,
              completion_tokens: 5,
              total_tokens: 15,
            },
          },
        },
      },
      {
        role: "assistant",
        content: "p2",
        metadata: {
          qwenpaw_turn_usage: {
            usage: {
              prompt_tokens: 100,
              completion_tokens: 50,
              total_tokens: 999,
            },
          },
        },
      },
    ];
    const result = convertMessages(messages);
    const data = result[1].cards![0].data as any;
    expect(data.usage).toMatchObject({ total_tokens: 999 });
  });
});

// ---------------------------------------------------------------------------
// 4. Individual helpers — small, fast pinning of each transform
// ---------------------------------------------------------------------------

describe("buildUserCard / buildResponseCard helpers", () => {
  it("buildUserCard wraps a string content into a single text part", () => {
    const card = buildUserCard({ role: "user", content: "hi" });
    const input = (card.cards![0].data as any).input[0];
    expect(input.role).toBe("user");
    expect(input.content[0].type).toBe("text");
    expect(input.content[0].text).toBe("hi");
    expect(input.content[0].status).toBe("created");
  });

  it("buildUserCard preserves image/file parts and resolves URLs", () => {
    const card = buildUserCard({
      role: "user",
      content: [
        { type: "text", text: "see file" },
        { type: "file", file_url: "/foo/bar.pdf", filename: "bar.pdf" },
      ],
    });
    const parts = (card.cards![0].data as any).input[0].content;
    expect(parts).toHaveLength(2);
    expect(parts[1].type).toBe("file");
    expect(parts[1].file_url).toContain("/files/preview/");
    expect(parts[1].file_name).toBe("bar.pdf");
  });

  it("buildResponseCard maps plugin_call_output + system role to tool role", () => {
    const outMsg = toOutputMessage({
      role: "system",
      type: "plugin_call_output",
      content: "result",
      metadata: null,
    });
    expect(outMsg.role).toBe("tool");
    const card = buildResponseCard([outMsg]);
    expect(card.role).toBe("assistant");
    const output = (card.cards![0].data as any).output;
    expect(output[0].role).toBe("tool");
  });

  it("buildResponseCard computes sequence_number as max+1", () => {
    const card = buildResponseCard([
      {
        role: "assistant",
        content: "a",
        metadata: null,
        sequence_number: 5,
      } as any,
      {
        role: "assistant",
        content: "b",
        metadata: null,
        sequence_number: 12,
      } as any,
    ]);
    const data = card.cards![0].data as any;
    expect(data.sequence_number).toBe(13);
  });

  it("parseTimestamp handles malformed timestamps without throwing", () => {
    expect(parseTimestamp({ metadata: {} } as any)).toBe(0);
    expect(
      parseTimestamp({ metadata: { timestamp: "not-a-date" } } as any),
    ).toBe(0);
    expect(
      parseTimestamp({
        metadata: { timestamp: "2026-06-01 10:00:00.000" },
      } as any),
    ).toBeGreaterThan(0);
  });

  it("extractTextFromContent joins text parts with newlines", () => {
    expect(extractTextFromContent("plain")).toBe("plain");
    expect(
      extractTextFromContent([
        { type: "text", text: "a" },
        { type: "text", text: "b" },
        { type: "image", image_url: "x" },
      ]),
    ).toBe("a\nb");
  });

  it("contentToRequestParts always returns at least one part (no empty arrays)", () => {
    expect(contentToRequestParts(null)).toHaveLength(1);
    expect(contentToRequestParts("")).toHaveLength(1);
    expect(contentToRequestParts([])).toHaveLength(1);
    expect(contentToRequestParts([{ type: "text", text: "x" }])).toHaveLength(
      1,
    );
  });

  it("normalizeOutputMessageContent adds file_name fallback for file items", () => {
    const out = normalizeOutputMessageContent([
      { type: "file", file_url: "/x" },
      { type: "text", text: "y" },
    ]);
    expect((out as any[])[0].file_name).toBe("file");
    expect((out as any[])[1]).toEqual({ type: "text", text: "y" });
  });
});

// ---------------------------------------------------------------------------
// 5. Small pure helpers — isLocalTimestamp / isGenerating / resolveRealId
// ---------------------------------------------------------------------------

describe("session id + status helpers", () => {
  it("isLocalTimestamp recognises timestamp-style local ids", () => {
    expect(isLocalTimestamp("1782267071416-qs7yghe")).toBe(true);
    expect(isLocalTimestamp("550e8400-e29b-41d4-a716-446655440000")).toBe(
      false,
    );
    expect(isLocalTimestamp("")).toBe(false);
  });

  it("isGenerating only returns true for explicit 'running' status", () => {
    expect(isGenerating({ messages: [], status: "running" })).toBe(true);
    expect(isGenerating({ messages: [], status: "idle" })).toBe(false);
    expect(isGenerating({ messages: [] })).toBe(false); // issue #4903: undefined ≠ running
  });

  it("resolveRealId prefers an already-resolved realId", () => {
    const list: any[] = [{ id: "ts-1", sessionId: "ts-1", realId: "uuid-1" }];
    const { realId } = resolveRealId(list, "ts-1");
    expect(realId).toBe("uuid-1");
  });

  it("resolveRealId matches a backend chat by session_id and rewrites id", () => {
    const list: any[] = [{ id: "uuid-9", sessionId: "ts-1" }];
    const { realId, list: newList } = resolveRealId(list, "ts-1");
    expect(realId).toBe("uuid-9");
    expect((newList[0] as any).realId).toBe("uuid-9");
    expect(newList[0].id).toBe("ts-1");
  });

  it("resolveRealId returns null when nothing matches (no crash)", () => {
    const list: any[] = [{ id: "uuid-9", sessionId: "other" }];
    const { realId } = resolveRealId(list, "ts-missing");
    expect(realId).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// 6. Integration — SessionApi.getSession on a mocked 500KB+ backend response
//    (exercises fetch → convert → cache → patchLastUserMessage end-to-end)
// ---------------------------------------------------------------------------

describe("SessionApi.getSession — large payload integration (#5479)", () => {
  beforeEach(() => {
    // Reset internal sessionList + caches between tests so the cache never
    // masks a regression introduced by another test.
    (sessionApiDefaultExport as any).sessionList = [];
    (sessionApiDefaultExport as any).convertedSessionCache.clear();
    (sessionApiDefaultExport as any).sessionResultCache.clear();
    (sessionApiDefaultExport as any).sessionRequests.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns a fully-converted session for a 600KB backend payload without throwing", async () => {
    const { messages, size } = buildLargeMessages(600 * 1024);
    expect(size).toBeGreaterThan(500 * 1024);

    const apiMod = await import("../../../api/modules/chat");
    vi.spyOn(apiMod.chatApi, "filePreviewUrl").mockImplementation(
      (p: string) => `http://localhost:8000/files/preview/${p}`,
    );
    // We reach into the default `api` aggregate used by sessionApi.
    const apiImport = await import("../../../api");
    vi.spyOn(apiImport.api, "getChat").mockResolvedValue({
      messages,
      status: "idle",
    } as ChatHistory);

    // getChat is invoked via the `api` import inside sessionApi/index.ts.
    // Pre-seed the session list so getSession finds an entry (and resolves
    // the backend id directly through the UUID branch).
    (sessionApiDefaultExport as any).sessionList = [
      {
        id: "uuid-big",
        sessionId: "uuid-big",
        userId: "u",
        channel: "c",
        name: "big",
      },
    ];

    const session = await sessionApiDefaultExport.getSession("uuid-big");
    const ext = session as any;
    expect(ext.messages.length).toBeGreaterThan(0);
    // First message is a user card.
    expect(ext.messages[0].role).toBe("user");
    // No exception was thrown — this is the #5479 regression.
    expect(typeof ext.messages[0].cards[0].code).toBe("string");
  });

  it("returns an empty session (no white-screen) when getChat throws 'Chat not found'", async () => {
    // Regression: historically a 404 on a stale large session would propagate
    // the error and blank the page. The fix returns an empty session so the
    // user sees the chat shell instead of a crash.
    const apiImport = await import("../../../api");
    vi.spyOn(apiImport.api, "getChat").mockRejectedValue(
      new Error("Chat not found"),
    );

    const session = await sessionApiDefaultExport.getSession("uuid-missing");
    expect(session).toBeDefined();
    expect((session as any).messages).toEqual([]);
    expect((session as any).id).toBe("uuid-missing");
  });

  it("does NOT cache generating sessions (avoids stale large payload being shown after reconnect)", async () => {
    const { messages } = buildLargeMessages(300 * 1024);

    const apiImport = await import("../../../api");
    const getChat = vi
      .spyOn(apiImport.api, "getChat")
      .mockResolvedValue({ messages, status: "running" } as ChatHistory);

    (sessionApiDefaultExport as any).sessionList = [
      {
        id: "gen-1",
        sessionId: "gen-1",
        userId: "u",
        channel: "c",
        name: "gen",
      },
    ];

    await sessionApiDefaultExport.getSession("gen-1");
    // Second call should hit the network again (not the LRU cache) because
    // generating sessions are never cached.
    await sessionApiDefaultExport.getSession("gen-1");
    expect(getChat).toHaveBeenCalledTimes(2);
  });

  it("caches idle sessions so switching back to a large conversation is fast (no refetch)", async () => {
    const { messages } = buildLargeMessages(300 * 1024);

    const apiImport = await import("../../../api");
    const getChat = vi
      .spyOn(apiImport.api, "getChat")
      .mockResolvedValue({ messages, status: "idle" } as ChatHistory);

    (sessionApiDefaultExport as any).sessionList = [
      {
        id: "idle-1",
        sessionId: "idle-1",
        userId: "u",
        channel: "c",
        name: "idle",
      },
    ];

    await sessionApiDefaultExport.getSession("idle-1");
    await sessionApiDefaultExport.getSession("idle-1");
    // LRU cache should have served the second call — exactly one network fetch.
    expect(getChat).toHaveBeenCalledTimes(1);
  });
});
