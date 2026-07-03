import { describe, expect, it } from "vitest";
import {
  DEFAULT_QUEUE_AGENT_ID,
  buildAgentScopedQueueSessionId,
  getQueueAgentId,
  stripQueueAgentPrefix,
} from "../chatSessionIds";

describe("chatSessionIds", () => {
  it("extracts agent id and raw session id from queue-scoped ids", () => {
    const sessionId = buildAgentScopedQueueSessionId("chat-1", "agent-a");

    expect(getQueueAgentId(sessionId)).toBe("agent-a");
    expect(stripQueueAgentPrefix(sessionId)).toBe("chat-1");
  });

  it("treats the default queue agent prefix as no explicit agent", () => {
    const sessionId = buildAgentScopedQueueSessionId(
      "chat-1",
      DEFAULT_QUEUE_AGENT_ID,
    );

    expect(getQueueAgentId(sessionId)).toBeUndefined();
    expect(stripQueueAgentPrefix(sessionId)).toBe("chat-1");
  });
});
