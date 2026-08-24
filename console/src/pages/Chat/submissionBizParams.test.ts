import { describe, expect, it } from "vitest";
import {
  buildSubmissionBizParams,
  enforceSubmissionIdentity,
  getSubmissionAgentId,
  getSubmissionChatId,
  getSubmissionIdentity,
  getSubmissionSdkSessionId,
  getSubmissionSessionId,
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
});
