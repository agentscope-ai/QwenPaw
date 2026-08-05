import { describe, expect, it } from "vitest";
import type { InboxEvent } from "../api/modules/console";
import { INBOX_EVENT_QUERY_LIMIT, isPushMessageEvent } from "./inboxEvents";

function event(sourceType: string): InboxEvent {
  return {
    id: sourceType,
    agent_id: "default",
    source_type: sourceType,
    source_id: "source",
    event_type: "test",
    status: "success",
    severity: "info",
    title: "Test",
    body: "Test",
    read: false,
    created_at: 1,
  };
}

describe("inboxEvents", () => {
  it("uses the shared page size for inbox counters", () => {
    expect(INBOX_EVENT_QUERY_LIMIT).toBe(200);
  });

  it("matches the push-message sources shown by the Inbox", () => {
    expect(
      ["cron", "heartbeat", "memory", "skill_autoupdate"].every((source) =>
        isPushMessageEvent(event(source)),
      ),
    ).toBe(true);
    expect(isPushMessageEvent(event("approval"))).toBe(false);
    expect(isPushMessageEvent(event("manual"))).toBe(false);
  });
});
