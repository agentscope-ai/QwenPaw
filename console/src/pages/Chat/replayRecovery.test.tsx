import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import AgentScopeRuntimeResponseBuilder from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/Response/Builder";
import { renderWithProviders } from "@/test/common_setup";
import { HostResponseCard } from "./HostBubbles";
import { wrapChatResponseUsageStream } from "./turnUsage";
import { sdkRateLimitErrorPayload } from "./replayRecovery";
import { useTurnUsageStore } from "./turnUsageStore";

const encoder = new TextEncoder();

function sse(payload: Record<string, unknown>, newline = "\n") {
  return `data: ${JSON.stringify(payload)}${newline}${newline}`;
}

function responseFromChunks(chunks: string[]) {
  return new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        for (const chunk of chunks) {
          controller.enqueue(encoder.encode(chunk));
        }
        controller.close();
      },
    }),
    {
      headers: {
        "content-length": "9999",
        "content-type": "text/event-stream",
      },
    },
  );
}

async function readSsePayloads(response: Response) {
  const text = await response.text();
  return text
    .split(/\r?\n\r?\n/)
    .map((block) => block.trim())
    .filter(Boolean)
    .map((block) => JSON.parse(block.slice(block.indexOf("data:") + 5)));
}

describe("replay truncation recovery", () => {
  it("forwards only the canonical response to the real SDK builder", async () => {
    const completed = {
      id: "response-1",
      object: "response",
      status: "completed",
      output: [
        {
          id: "message-1",
          object: "message",
          role: "assistant",
          status: "completed",
          type: "message",
          content: [
            {
              object: "content",
              type: "text",
              status: "completed",
              text: "canonical response",
            },
          ],
        },
      ],
    };
    const usage = {
      type: "turn_usage",
      usage: { total_tokens: 1 },
    };
    const body = [
      sse({ type: "replay_truncated" }),
      sse({ object: "message", type: "message" }),
      sse(completed, "\r\n"),
      sse(usage),
    ].join("");
    const split = Math.floor(body.length / 2);
    const updateMessage = vi.fn();
    const chatRef = {
      current: {
        messages: {
          getMessages: () => [
            {
              role: "assistant",
              cards: [
                {
                  code: "AgentScopeRuntimeResponseCard",
                  data: {},
                },
              ],
            },
          ],
          updateMessage,
        },
      },
    } as any;
    const wrapped = wrapChatResponseUsageStream(
      responseFromChunks([body.slice(0, split), body.slice(split)]),
      chatRef,
    );

    expect(wrapped.headers.has("content-length")).toBe(false);
    const payloads = await readSsePayloads(wrapped);
    expect(payloads).toEqual([completed]);
    expect(useTurnUsageStore.getState().snapshot?.usage?.total_tokens).toBe(1);
    expect(updateMessage).toHaveBeenCalledOnce();

    const builder = new AgentScopeRuntimeResponseBuilder({
      id: "response-1",
      status: "created" as any,
      created_at: 0,
    });
    const result = builder.handle(payloads[0]);
    expect(result.status).toBe("completed");
    renderWithProviders(<HostResponseCard data={result as any} />);
    expect(screen.getByTestId("chat-card-mock")).toBeInTheDocument();
  });

  it("forwards rate-limit and converts it into a failed SDK response", async () => {
    const rateLimited = {
      type: "rate_limited",
      error: "quota exceeded",
    };
    const wrapped = wrapChatResponseUsageStream(
      responseFromChunks([sse(rateLimited)]),
      { current: null },
    );
    const payloads = await readSsePayloads(wrapped);
    expect(payloads).toEqual([rateLimited]);

    const parsed = sdkRateLimitErrorPayload(payloads[0], "rate limited");
    const builder = new AgentScopeRuntimeResponseBuilder({
      id: "response-1",
      status: "created" as any,
      created_at: 0,
    });

    const result = builder.handle(parsed as any);
    expect(result.status).toBe("failed");
    expect(result.output[result.output.length - 1]?.message).toBe(
      "quota exceeded",
    );
  });
});
