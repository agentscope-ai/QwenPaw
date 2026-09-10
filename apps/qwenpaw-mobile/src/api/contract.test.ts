import assert from "node:assert/strict";
import test from "node:test";

import {
  DEFAULT_NOTIFICATION_PREFERENCES,
  notificationKindForInboxEvent,
  notificationPriority,
  parseMobileNotificationData,
  parseNotificationPreferences,
} from "@qwenpaw/api-contract";

test("parses a versioned mobile notification payload", () => {
  assert.deepEqual(
    parseMobileNotificationData({
      version: 1,
      kind: "approval_required",
      workspace_key: "workspace-key",
      agent_id: "default",
      chat_id: "chat-1",
    }),
    {
      version: 1,
      kind: "approval_required",
      workspace_key: "workspace-key",
      agent_id: "default",
      chat_id: "chat-1",
      session_id: undefined,
      approval_request_id: undefined,
      inbox_event_id: undefined,
    },
  );
  assert.equal(parseMobileNotificationData({ version: 2 }), null);
});

test("validates notification preferences", () => {
  assert.deepEqual(
    parseNotificationPreferences(DEFAULT_NOTIFICATION_PREFERENCES),
    DEFAULT_NOTIFICATION_PREFERENCES,
  );
  assert.equal(
    parseNotificationPreferences({
      ...DEFAULT_NOTIFICATION_PREFERENCES,
      preview: "secret",
    }),
    null,
  );
});

test("maps inbox state and orders actionable notification kinds", () => {
  assert.equal(
    notificationKindForInboxEvent({
      event_type: "cron_finished",
      status: "failed",
      severity: "error",
    }),
    "run_failed",
  );
  assert.ok(
    notificationPriority("approval_required") >
      notificationPriority("run_completed"),
  );
});
