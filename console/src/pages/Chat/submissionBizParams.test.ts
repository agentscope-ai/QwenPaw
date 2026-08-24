import { describe, expect, it } from "vitest";
import {
  buildSubmissionBizParams,
  enforceSubmissionSessionId,
  getSubmissionChatId,
  getSubmissionSessionId,
} from "./submissionBizParams";

describe("submissionBizParams", () => {
  it("keeps the session captured when the message was submitted", () => {
    const bizParams = buildSubmissionBizParams("session-a", {
      source: "console_chat",
      chat_id: "chat-a",
    });

    expect(getSubmissionSessionId(bizParams, "session-b")).toBe("session-a");
    expect(getSubmissionChatId(bizParams)).toBe("chat-a");
    expect(bizParams.request_context).toEqual({
      source: "console_chat",
      chat_id: "chat-a",
    });
  });

  it("restores the frozen session after a payload transform", () => {
    const bizParams = buildSubmissionBizParams("session-a");
    const transformedPayload = { session_id: "session-b", input: [] };

    expect(
      enforceSubmissionSessionId(transformedPayload, bizParams, "session-b")
        .session_id,
    ).toBe("session-a");
  });

  it("uses the normal send identity when no valid snapshot exists", () => {
    expect(getSubmissionSessionId(undefined, "session-b")).toBe("session-b");
    expect(getSubmissionSessionId({ session_id: "" }, "session-b")).toBe(
      "session-b",
    );
  });
});
