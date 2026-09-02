import { describe, expect, it } from "vitest";
import {
  buildChatSubmissionContext,
  resolveChatRequestSnapshot,
} from "./sdkRequestSnapshot";

describe("SDK 1.2 request snapshots", () => {
  it("prefers the immutable SDK snapshot over stale host state", () => {
    expect(
      resolveChatRequestSnapshot(
        {
          session_id: "snapshot-session",
          user_id: "snapshot-user",
          channel: "snapshot-channel",
          agent_id: "snapshot-agent",
          context: { source: "queue" },
        },
        {
          sessionId: "stale-session",
          userId: "stale-user",
          channel: "stale-channel",
        },
        {
          session_id: "message-session",
          user_id: "message-user",
          channel: "message-channel",
        },
        "stale-agent",
      ),
    ).toEqual({
      sessionId: "snapshot-session",
      userId: "snapshot-user",
      channel: "snapshot-channel",
      agentId: "snapshot-agent",
      context: { source: "queue" },
    });
  });

  it("stores direct-send identity in the SDK business context", () => {
    expect(
      buildChatSubmissionContext(
        { source: "sender" },
        {
          sessionId: "session-1",
          userId: "user-1",
          channel: "console",
        },
        "agent-1",
      ),
    ).toEqual({
      source: "sender",
      session_id: "session-1",
      user_id: "user-1",
      channel: "console",
      agent_id: "agent-1",
    });
  });

  it("keeps the backend runtime session when SDK session_id is the chat id", () => {
    expect(
      resolveChatRequestSnapshot(
        {
          session_id: "chat-uuid",
          context: { session_id: "runtime-session" },
        },
        { sessionId: "stale-runtime" },
        {},
        "default",
      ).sessionId,
    ).toBe("runtime-session");
  });
});
