import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import AgentScopeRuntimeResponseBuilder from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/Response/Builder";
import { renderWithProviders } from "@/test/common_setup";
import { HostResponseCard } from "./HostBubbles";
import { filterReplayPayload } from "./replayRecovery";

describe("replay truncation recovery", () => {
  it("renders the canonical response through the real SDK builder", () => {
    const builder = new AgentScopeRuntimeResponseBuilder({
      id: "response-1",
      status: "created" as any,
      created_at: 0,
    });
    let streamTruncated = false;

    for (const payload of [
      { type: "replay_truncated" },
      { object: "message", type: "message" },
    ]) {
      const filtered = filterReplayPayload(payload, streamTruncated);
      streamTruncated = filtered.streamTruncated;
      expect(() => builder.handle(filtered.payload as any)).not.toThrow();
    }

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
    const filtered = filterReplayPayload(completed, streamTruncated);
    const result = builder.handle(filtered.payload as any);

    expect(filtered.streamTruncated).toBe(false);
    expect(result.status).toBe("completed");
    renderWithProviders(<HostResponseCard data={result as any} />);
    expect(screen.getByTestId("chat-card-mock")).toBeInTheDocument();
  });
});
