import { describe, expect, it } from "vitest";
import { resolveChatRequestContext } from "../chatRequestContext";

describe("resolveChatRequestContext", () => {
  it("prefers queue item context over the current selected agent and session", () => {
    const context = resolveChatRequestContext({
      data: {
        session_id: "queued-session",
        user_id: "queued-user",
        channel: "queued-channel",
        agent_id: "queued-agent",
      },
      session: {
        session_id: "message-session",
        user_id: "message-user",
        channel: "message-channel",
      },
      selectedAgent: "current-agent",
      getSessionIdentity: () => ({
        sessionId: "identity-session",
        userId: "identity-user",
        channel: "identity-channel",
      }),
      defaultUserId: "default-user",
      defaultChannel: "default-channel",
    });

    expect(context).toEqual({
      sessionId: "queued-session",
      userId: "queued-user",
      channel: "queued-channel",
      agentId: "queued-agent",
    });
  });

  it("uses the selected agent and resolved session identity for direct sends", () => {
    const context = resolveChatRequestContext({
      data: {},
      session: {
        session_id: "message-session",
      },
      selectedAgent: "current-agent",
      getSessionIdentity: (sessionId?: string) => ({
        sessionId: `identity:${sessionId}`,
        userId: "identity-user",
        channel: "identity-channel",
      }),
      defaultUserId: "default-user",
      defaultChannel: "default-channel",
    });

    expect(context).toEqual({
      sessionId: "identity:message-session",
      userId: "identity-user",
      channel: "identity-channel",
      agentId: "current-agent",
    });
  });

  it("falls back to message session and defaults when no identity is available", () => {
    const context = resolveChatRequestContext({
      data: {},
      session: {
        session_id: "message-session",
      },
      selectedAgent: "current-agent",
      getSessionIdentity: () => ({
        sessionId: "",
        userId: "",
        channel: "",
      }),
      defaultUserId: "default-user",
      defaultChannel: "default-channel",
    });

    expect(context).toEqual({
      sessionId: "message-session",
      userId: "default-user",
      channel: "default-channel",
      agentId: "current-agent",
    });
  });
});
