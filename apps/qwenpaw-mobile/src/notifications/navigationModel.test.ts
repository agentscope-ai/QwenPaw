import assert from "node:assert/strict";
import test from "node:test";

import type { MobileNotificationData } from "@qwenpaw/api-contract";

import { notificationDestination } from "./navigationModel";

const base: MobileNotificationData = {
  version: 1,
  kind: "run_completed",
  workspace_key: "workspace",
  agent_id: "default",
};

test("approval notifications target the conversation inbox", () => {
  assert.deepEqual(
    notificationDestination({
      ...base,
      kind: "approval_required",
      approval_request_id: "approval-one",
    }),
    { kind: "approval" },
  );
});

test("chat notifications target their exact conversation", () => {
  assert.deepEqual(
    notificationDestination({
      ...base,
      chat_id: "chat-one",
    }),
    { kind: "chat", chatId: "chat-one" },
  );
});

test("non-chat inbox notifications target the workbench", () => {
  assert.deepEqual(notificationDestination(base), { kind: "workbench" });
});
