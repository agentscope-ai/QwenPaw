import { describe, expect, it } from "vitest";

import { createReconnectRequestPayload } from "../index";

describe("reconnect access scope", () => {
  it("sends the resolved conversation id with the trusted session identity", () => {
    expect(
      createReconnectRequestPayload({
        backendSessionId: "console:user-a:session-a",
        userId: "user-a",
        channel: "console",
        conversationId: "cd96989a-7a2b-4b51-90e8-d9145e228361",
      }),
    ).toEqual({
      reconnect: true,
      session_id: "console:user-a:session-a",
      user_id: "user-a",
      channel: "console",
      conversation_id: "cd96989a-7a2b-4b51-90e8-d9145e228361",
    });
  });
});
