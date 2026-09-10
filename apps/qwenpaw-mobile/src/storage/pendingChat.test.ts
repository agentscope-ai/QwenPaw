import assert from "node:assert/strict";
import test from "node:test";

import type { DisplayMessage } from "../api/types";
import {
  mergePendingChatTurn,
  pendingUserMessagePersisted,
  type PendingChatTurn,
} from "./pendingChat";

const userMessage: DisplayMessage = {
  id: "user-local",
  role: "user",
  kind: "message",
  parts: [{ type: "text", text: "还在执行吗" }],
};
const pending: PendingChatTurn = {
  responseId: "response-local",
  userMessage,
};

test("restores a pending user query and response placeholder", () => {
  const merged = mergePendingChatTurn([], pending);

  assert.deepEqual(merged[0], userMessage);
  assert.equal(merged[1]?.id, "response-local");
  assert.equal(merged[1]?.pending, true);
});

test("does not duplicate a pending user query already in history", () => {
  const history = [{ ...userMessage, id: "server-user" }];
  const merged = mergePendingChatTurn(history, pending);

  assert.equal(pendingUserMessagePersisted(history, pending), true);
  assert.equal(merged.filter((message) => message.role === "user").length, 1);
});

test("matches the submitted loop command stored by the backend", () => {
  const loopPending = {
    ...pending,
    submittedText: "/loop off \u8fd8\u5728\u6267\u884c\u5417",
  };
  const history = [{
    ...userMessage,
    id: "server-user",
    parts: [{ type: "text" as const, text: "/loop off \u8fd8\u5728\u6267\u884c\u5417" }],
  }];

  assert.equal(pendingUserMessagePersisted(history, loopPending), true);
});
