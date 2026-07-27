/**
 * Giant turn splitting — convertMessages must split a turn with many
 * outputs into multiple ResponseCards.
 *
 * Rationale: the chat SDK paginates history at message-card granularity
 * (10 cards per page). A single ResponseCard holding hundreds of tool
 * outputs (e.g. a long ComfyUI run) bypasses that window entirely and
 * forces a full render of the whole result set when the conversation is
 * opened. Splitting giant turns into bounded chunks lets the built-in
 * pagination actually limit render cost.
 *
 * Compatibility pinned here:
 *   - turn usage / context usage must land ONLY on the last chunk, so
 *     tail-scanning consumers (extractLatestSnapshotFromCards,
 *     hydrateTurnUsageFromMessages) keep working unchanged.
 *   - output order must be preserved across chunks.
 *   - turns at or below the threshold keep producing exactly one card.
 */
import { describe, it, expect, vi } from "vitest";
import type { Message } from "../../../api/types/chat";

// Mock chatApi.filePreviewUrl so toDisplayUrl() is deterministic and does
// not touch real config/token code paths.
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
import { extractLatestSnapshotFromCards } from "../turnUsage";

const { convertMessages, extractTextFromContent } = __test__;
const MAX_OUTPUTS = __test__.MAX_OUTPUTS_PER_RESPONSE_CARD;
const MAX_CONTENT_BLOCKS = __test__.MAX_CONTENT_BLOCKS_PER_RESPONSE_CARD;
const MAX_PAYLOAD_CHARS = __test__.MAX_PAYLOAD_CHARS_PER_RESPONSE_CARD;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** One user message followed by `n` assistant outputs; the LAST output
 *  carries turn usage metadata (mirrors real backend behaviour). */
function buildTurn(n: number): Message[] {
  const messages: Message[] = [
    {
      role: "user",
      content: "run the workflow",
      metadata: { timestamp: "2026-06-01 10:00:00.000" },
    },
  ];
  for (let s = 0; s < n; s++) {
    messages.push({
      role: "assistant",
      content: [{ type: "text", text: `out-${s}` }],
      metadata:
        s === n - 1
          ? {
              qwenpaw_turn_usage: {
                usage: {
                  prompt_tokens: 100,
                  completion_tokens: 50,
                  total_tokens: 150,
                },
                context_usage: {
                  estimated_tokens: 200,
                  max_input_length: 8000,
                  context_usage_ratio: 0.025,
                },
              },
            }
          : {},
    });
  }
  return messages;
}

const cardData = (card: any) => card.cards?.[0]?.data as any;

const assistantCards = (messages: Message[]) =>
  convertMessages(messages).filter((message) => message.role === "assistant");

// ---------------------------------------------------------------------------
// Splitting behaviour
// ---------------------------------------------------------------------------

describe("convertMessages — giant turn splitting", () => {
  it("keeps a turn at the threshold as a single card", () => {
    const result = convertMessages(buildTurn(MAX_OUTPUTS));
    expect(result).toHaveLength(2); // user + one assistant card
    expect(cardData(result[1]).output).toHaveLength(MAX_OUTPUTS);
  });

  it("splits a turn one above the threshold into two cards", () => {
    const result = convertMessages(buildTurn(MAX_OUTPUTS + 1));
    expect(result).toHaveLength(3); // user + two assistant cards
    expect(cardData(result[1]).output).toHaveLength(MAX_OUTPUTS);
    expect(cardData(result[2]).output).toHaveLength(1);
  });

  it("splits a giant turn into ceil(n / threshold) cards", () => {
    const n = MAX_OUTPUTS * 2 + 5;
    const result = convertMessages(buildTurn(n));
    // user card + 3 assistant chunks (20 / 20 / 5 for threshold 20)
    expect(result).toHaveLength(4);
    for (let i = 1; i < result.length; i++) {
      expect(result[i].role).toBe("assistant");
      expect(result[i].cards![0].code).toBe("AgentScopeRuntimeResponseCard");
      expect((result[i] as any).msgStatus).toBe("finished");
    }
  });

  it("preserves output order across chunks", () => {
    const n = MAX_OUTPUTS * 2 + 5;
    const result = convertMessages(buildTurn(n));
    const texts: string[] = [];
    for (let i = 1; i < result.length; i++) {
      for (const out of cardData(result[i]).output) {
        texts.push(extractTextFromContent(out.content));
      }
    }
    expect(texts).toHaveLength(n);
    expect(texts[0]).toBe("out-0");
    expect(texts[n - 1]).toBe(`out-${n - 1}`);
    // Strictly increasing sequence — no reordering or loss.
    for (let s = 0; s < n; s++) {
      expect(texts[s]).toBe(`out-${s}`);
    }
  });

  it("does not split across user boundaries", () => {
    const messages = [...buildTurn(MAX_OUTPUTS + 5), ...buildTurn(3)];
    const result = convertMessages(messages);
    // turn1: user + 2 chunks; turn2: user + 1 card
    expect(result.map((m) => m.role)).toEqual([
      "user",
      "assistant",
      "assistant",
      "user",
      "assistant",
    ]);
    expect(cardData(result[4]).output).toHaveLength(3);
  });

  it("splits one assistant message with hundreds of images", () => {
    const imageCount = MAX_CONTENT_BLOCKS * 25;
    const cards = assistantCards([
      {
        role: "user",
        content: "show results",
      },
      {
        id: "images",
        role: "assistant",
        type: "message",
        content: Array.from({ length: imageCount }, (_, index) => ({
          type: "image",
          image_url: `/result-${index}.png`,
        })),
      },
    ]);

    expect(cards).toHaveLength(25);
    const images = cards.flatMap((card) =>
      cardData(card).output.flatMap((output: any) => output.content),
    );
    expect(images).toHaveLength(imageCount);
    expect(images[0].image_url).toBe("/result-0.png");
    expect(images[images.length - 1].image_url).toBe(
      `/result-${imageCount - 1}.png`,
    );
  });

  it("splits fewer than 20 outputs when their combined payload is large", () => {
    const cards = assistantCards([
      { role: "user", content: "go" },
      ...Array.from({ length: 6 }, (_, index) => ({
        id: `large-${index}`,
        role: "assistant",
        type: "message",
        content: [
          {
            type: "text",
            text: "x".repeat(Math.floor(MAX_PAYLOAD_CHARS / 2)),
          },
        ],
      })),
    ]);

    expect(cards.length).toBeGreaterThan(1);
    expect(
      cards.every((card) => cardData(card).output.length < MAX_OUTPUTS),
    ).toBe(true);
  });

  it("defers one atomic giant text instead of mounting it initially", () => {
    const cards = assistantCards([
      { role: "user", content: "go" },
      {
        id: "giant-text",
        role: "assistant",
        type: "message",
        content: [
          { type: "text", text: "x".repeat(MAX_PAYLOAD_CHARS + 1) },
        ],
      },
    ]);

    expect(cards).toHaveLength(1);
    expect(cardData(cards[0]).qwenpaw_deferred_render).toBe(true);
  });

  it("keeps a giant tool pair together and defers its output", () => {
    const cards = assistantCards([
      { role: "user", content: "run tool" },
      {
        id: "tool-call",
        role: "assistant",
        type: "plugin_call",
        content: [
          {
            type: "data",
            data: { call_id: "call-1", name: "comfyui", arguments: "{}" },
          },
        ],
      },
      {
        id: "tool-output",
        role: "system",
        type: "plugin_call_output",
        content: [
          {
            type: "data",
            data: {
              call_id: "call-1",
              name: "comfyui",
              output: "x".repeat(MAX_PAYLOAD_CHARS + 1),
            },
          },
        ],
      },
    ]);

    expect(cards).toHaveLength(1);
    expect(cardData(cards[0]).output).toHaveLength(2);
    expect(cardData(cards[0]).qwenpaw_deferred_render).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Turn usage compatibility
// ---------------------------------------------------------------------------

describe("giant turn splitting — turn usage stays on the last chunk", () => {
  it("attaches usage/context_usage only to the last chunk", () => {
    const result = convertMessages(buildTurn(MAX_OUTPUTS * 2 + 5));
    const chunks = result.slice(1);
    const last = chunks[chunks.length - 1];

    for (const chunk of chunks.slice(0, -1)) {
      expect(cardData(chunk).usage).toBeNull();
      expect(cardData(chunk).context_usage).toBeNull();
    }
    expect(cardData(last).usage).toMatchObject({ total_tokens: 150 });
    expect(cardData(last).context_usage).toMatchObject({
      estimated_tokens: 200,
    });
  });

  it("extractLatestSnapshotFromCards still resolves the turn usage", () => {
    const result = convertMessages(buildTurn(MAX_OUTPUTS * 3));
    const snap = extractLatestSnapshotFromCards(result);
    expect(snap).not.toBeNull();
    expect(snap!.usage).toMatchObject({ total_tokens: 150 });
    expect(snap!.context_usage).toMatchObject({ estimated_tokens: 200 });
  });

  it("single-card turns keep extracting usage as before", () => {
    const result = convertMessages(buildTurn(3));
    expect(cardData(result[1]).usage).toMatchObject({ total_tokens: 150 });
    const snap = extractLatestSnapshotFromCards(result);
    expect(snap!.usage).toMatchObject({ total_tokens: 150 });
  });
});
