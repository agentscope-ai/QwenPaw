import { describe, expect, it } from "vitest";

import {
  DEFAULT_QUEUE_AGENT_ID,
  resolveAgentScopedQueueSessionId,
  resolveBackendChatSessionId,
  stripQueueAgentPrefix,
} from "./chatSessionIds";

const backendByRouteId = new Map([
  ["route-test-1", "backend-test-1"],
  ["route-test-2", "backend-test-2"],
  ["same-route", "same-backend-session"],
]);

const getBackendSessionId = (sessionId: string) =>
  backendByRouteId.get(sessionId) || sessionId;

describe("chat session id helpers", () => {
  it("keeps same-agent queues isolated by backend chat session", () => {
    const test1QueueId = resolveAgentScopedQueueSessionId(
      "route-test-1",
      "agent-a",
      getBackendSessionId,
    );
    const test2QueueId = resolveAgentScopedQueueSessionId(
      "route-test-2",
      "agent-a",
      getBackendSessionId,
    );

    expect(test1QueueId).toBe("agent-a::backend-test-1");
    expect(test2QueueId).toBe("agent-a::backend-test-2");
    expect(test1QueueId).not.toBe(test2QueueId);
  });

  it("keeps different-agent queues isolated even for the same backend session", () => {
    const agentAQueueId = resolveAgentScopedQueueSessionId(
      "same-route",
      "agent-a",
      getBackendSessionId,
    );
    const agentBQueueId = resolveAgentScopedQueueSessionId(
      "same-route",
      "agent-b",
      getBackendSessionId,
    );

    expect(agentAQueueId).toBe("agent-a::same-backend-session");
    expect(agentBQueueId).toBe("agent-b::same-backend-session");
    expect(agentAQueueId).not.toBe(agentBQueueId);
  });

  it("strips agent-scoped queue ids before sending backend requests", () => {
    expect(stripQueueAgentPrefix("agent-a::route-test-1")).toBe(
      "route-test-1",
    );
    expect(
      resolveBackendChatSessionId(
        "agent-a::route-test-1",
        getBackendSessionId,
      ),
    ).toBe("backend-test-1");
  });

  it("uses a stable fallback queue agent id before the selected agent loads", () => {
    expect(
      resolveAgentScopedQueueSessionId(
        "route-test-1",
        undefined,
        getBackendSessionId,
      ),
    ).toBe(`${DEFAULT_QUEUE_AGENT_ID}::backend-test-1`);
  });
});
