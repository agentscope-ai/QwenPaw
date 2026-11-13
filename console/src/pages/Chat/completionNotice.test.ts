import { describe, expect, it } from "vitest";
import {
  AgentScopeRuntimeContentType,
  AgentScopeRuntimeMessageType,
  AgentScopeRuntimeRunStatus,
} from "@agentscope-ai/chat";
import {
  hasTruncatedModelOutput,
  type CompletionResponse,
} from "./completionNotice";

const truncated = {
  qwenpaw_model_completion: { finish_reason: "length", truncated: true },
};

function response(
  overrides: Partial<CompletionResponse> = {},
): CompletionResponse {
  return {
    id: "test",
    status: AgentScopeRuntimeRunStatus.Completed,
    output: [],
    ...overrides,
  } as CompletionResponse;
}

describe("incomplete answer notice", () => {
  it("recognizes live response metadata", () => {
    expect(hasTruncatedModelOutput(response({ metadata: truncated }))).toBe(
      true,
    );
  });

  it("recognizes persisted message metadata after history conversion", () => {
    expect(
      hasTruncatedModelOutput(
        response({
          output: [
            {
              id: "answer",
              role: "assistant",
              type: AgentScopeRuntimeMessageType.MESSAGE,
              status: AgentScopeRuntimeRunStatus.Completed,
              content: [
                {
                  type: AgentScopeRuntimeContentType.TEXT,
                  text: "partial",
                  status: AgentScopeRuntimeRunStatus.Completed,
                },
              ],
              metadata: { metadata: truncated },
            },
          ],
        }),
      ),
    ).toBe(true);
  });

  it.each([
    AgentScopeRuntimeRunStatus.InProgress,
    AgentScopeRuntimeRunStatus.Canceled,
    AgentScopeRuntimeRunStatus.Failed,
  ])("does not override the %s lifecycle", (status) => {
    expect(
      hasTruncatedModelOutput(response({ status, metadata: truncated })),
    ).toBe(false);
  });

  it("does not report ordinary or malformed completion data as truncated", () => {
    for (const metadata of [
      undefined,
      {},
      { qwenpaw_model_completion: "length" },
      { qwenpaw_model_completion: { truncated: "true" } },
      { qwenpaw_model_completion: { truncated: false } },
    ]) {
      expect(hasTruncatedModelOutput(response({ metadata }))).toBe(false);
    }
  });
});
