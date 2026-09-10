import assert from "node:assert/strict";
import test from "node:test";

import type { DisplayMessage } from "../api/types";
import { selectChatMessages } from "./selectors";

test("returns a stable empty message list for an unloaded chat", () => {
  const messages = {};

  assert.equal(
    selectChatMessages(messages, "chat-1"),
    selectChatMessages(messages, "chat-1"),
  );
});

test("returns the stored message list for a loaded chat", () => {
  const chatMessages: DisplayMessage[] = [
    {
      id: "message-1",
      role: "user",
      kind: "message",
      parts: [{ type: "text", text: "Hello" }],
    },
  ];

  assert.equal(
    selectChatMessages({ "chat-1": chatMessages }, "chat-1"),
    chatMessages,
  );
});
