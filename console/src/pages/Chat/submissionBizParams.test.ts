import { describe, expect, it } from "vitest";
import {
  buildSubmissionBizParams,
  enforceSubmissionIdentity,
  getSubmissionAgentId,
  getSubmissionChatId,
  getSubmissionConversationReference,
  getSubmissionIdentity,
  getQueueSubmissionTarget,
  getSubmissionSdkSessionId,
  getSubmissionSessionId,
  isSubmissionTargetReady,
  rebindSubmissionBizParams,
} from "./submissionBizParams";

const IDENTITY_A = {
  sessionId: "session-a",
  userId: "user-a",
  channel: "channel-a",
};

describe("submissionBizParams", () => {
  it("keeps the session captured when the message was submitted", () => {
    const bizParams = buildSubmissionBizParams(IDENTITY_A, {
      source: "console_chat",
      agent_id: "agent-a",
      chat_id: "chat-a",
      sdk_session_id: "sdk-a",
    });

    expect(getSubmissionSessionId(bizParams, "session-b")).toBe("session-a");
    expect(getSubmissionChatId(bizParams)).toBe("chat-a");
    expect(getSubmissionSdkSessionId(bizParams)).toBe("sdk-a");
    expect(getSubmissionAgentId(bizParams)).toBe("agent-a");
    expect(
      getSubmissionIdentity(bizParams, {
        sessionId: "session-b",
        userId: "user-b",
        channel: "channel-b",
      }),
    ).toEqual(IDENTITY_A);
    expect(bizParams.request_context).toEqual({
      source: "console_chat",
      agent_id: "agent-a",
      chat_id: "chat-a",
      sdk_session_id: "sdk-a",
    });
  });

  it("restores the frozen session after a payload transform", () => {
    const bizParams = buildSubmissionBizParams(IDENTITY_A);
    const transformedPayload = {
      session_id: "session-b",
      user_id: "user-b",
      channel: "channel-b",
      input: [],
    };

    expect(
      enforceSubmissionIdentity(transformedPayload, bizParams, {
        sessionId: "session-b",
        userId: "user-b",
        channel: "channel-b",
      }),
    ).toMatchObject({
      session_id: "session-a",
      user_id: "user-a",
      channel: "channel-a",
    });
  });

  it("uses the normal send identity when no valid snapshot exists", () => {
    expect(getSubmissionSessionId(undefined, "session-b")).toBe("session-b");
    expect(getSubmissionSessionId({ session_id: "" }, "session-b")).toBe(
      "session-b",
    );
  });

  it("rebinds a new-chat placeholder after the SDK creates a local session", () => {
    expect(
      rebindSubmissionBizParams(
        {
          session_id: "",
          user_id: "default",
          channel: "console",
          request_context: {
            source: "console_chat_queue",
            agent_id: "stale-agent",
            chat_id: "new",
            sdk_session_id: "new",
          },
        },
        IDENTITY_A,
        {
          agentId: "agent-a",
          chatId: "local-a",
          sdkSessionId: "local-a",
        },
      ),
    ).toEqual({
      session_id: "session-a",
      user_id: "user-a",
      channel: "channel-a",
      request_context: {
        source: "console_chat_queue",
        agent_id: "agent-a",
        chat_id: "local-a",
        sdk_session_id: "local-a",
      },
    });
  });

  it("never uses mutable page state as the request conversation", () => {
    const bizParams = buildSubmissionBizParams(IDENTITY_A, {
      agent_id: "agent-a",
      chat_id: "chat-a",
      sdk_session_id: "sdk-a",
    });

    expect(getSubmissionConversationReference(bizParams, "stale-chat-b")).toBe(
      "chat-a",
    );
    expect(
      getSubmissionConversationReference(
        {
          request_context: {
            chat_id: "new",
            sdk_session_id: "local-a",
          },
        },
        "stale-chat-b",
      ),
    ).toBe("local-a");
    expect(getSubmissionConversationReference(undefined)).toBeUndefined();
  });

  it("blocks a direct send while the new agent still has the old route", () => {
    expect(isSubmissionTargetReady(undefined, "agent-b", "chat-a", "")).toBe(
      false,
    );
  });

  it("accepts only frozen submissions matching the selected agent and route", () => {
    const bizParams = buildSubmissionBizParams(IDENTITY_A, {
      agent_id: "agent-a",
      chat_id: "chat-a",
      sdk_session_id: "sdk-a",
    });

    expect(isSubmissionTargetReady(bizParams, "agent-a", "chat-a", "")).toBe(
      true,
    );
    expect(isSubmissionTargetReady(bizParams, "agent-b", "chat-a", "")).toBe(
      false,
    );
    expect(isSubmissionTargetReady(bizParams, "agent-a", "chat-b", "")).toBe(
      false,
    );
  });

  it("resolves every queued item from its own immutable target", () => {
    const agent1Item = buildSubmissionBizParams(IDENTITY_A, {
      agent_id: "agent-1",
      chat_id: "chat-1",
      sdk_session_id: "sdk-1",
    });
    const agent2Item = buildSubmissionBizParams(
      {
        sessionId: "session-2",
        userId: "user-2",
        channel: "console",
      },
      {
        agent_id: "agent-2",
        chat_id: "chat-2",
        sdk_session_id: "sdk-2",
      },
    );

    expect(getQueueSubmissionTarget(agent1Item, "agent-1")).toMatchObject({
      agentId: "agent-1",
      conversationReference: "chat-1",
      identity: { sessionId: "session-a" },
    });
    expect(getQueueSubmissionTarget(agent2Item, "agent-2")).toMatchObject({
      agentId: "agent-2",
      conversationReference: "chat-2",
      identity: { sessionId: "session-2" },
    });
  });

  it("rejects a queue item whose agent header and snapshot disagree", () => {
    const test2Item = buildSubmissionBizParams(IDENTITY_A, {
      agent_id: "agent-2",
      chat_id: "chat-2",
      sdk_session_id: "sdk-2",
    });

    expect(getQueueSubmissionTarget(test2Item, "agent-1")).toBeUndefined();
  });

  it("keeps a new-chat placeholder unresolved until the SDK binds it", () => {
    const placeholder = buildSubmissionBizParams(
      { sessionId: "", userId: "default", channel: "console" },
      {
        agent_id: "agent-1",
        chat_id: "new",
        sdk_session_id: "new",
      },
    );

    expect(getSubmissionChatId(placeholder)).toBe("new");
    expect(getQueueSubmissionTarget(placeholder, "agent-1")).toBeUndefined();
  });
});
