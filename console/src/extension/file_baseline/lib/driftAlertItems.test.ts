import { describe, it, expect } from "vitest";
import {
  mapInboxEventsByAlertId,
  mergeAlertItems,
} from "./driftAlertItems";

describe("personaDriftAlertItems", () => {
  it("maps unread inbox persona events by alert id", () => {
    const mapped = mapInboxEventsByAlertId([
      {
        id: "evt-1",
        agent_id: "default",
        source_type: "file_baseline_protection",
        source_id: "alert-1",
        event_type: "file_baseline_drift",
        status: "pending_review",
        severity: "high",
        title: "Persona file changed",
        body: "SOUL.md drift",
        read: false,
        created_at: 1,
      },
    ]);
    expect(mapped.get("alert-1")?.id).toBe("evt-1");
  });

  it("merges open alerts with inbox metadata for notifier cards", () => {
    const inboxByAlertId = mapInboxEventsByAlertId([
      {
        id: "evt-1",
        agent_id: "default",
        source_type: "file_baseline_protection",
        source_id: "alert-1",
        event_type: "file_baseline_drift",
        status: "pending_review",
        severity: "high",
        title: "Persona file changed",
        body: "SOUL.md drift",
        read: false,
        created_at: 1,
      },
    ]);
    const merged = mergeAlertItems(
      [
        {
          alert_id: "alert-1",
          agent_id: "default",
          path: "SOUL.md",
          approved_sha256: "aaa",
          current_sha256: "bbb",
          provenance: "external_watch",
          status: "pending_review",
          detected_at: "2026-01-01T00:00:00Z",
        },
      ],
      inboxByAlertId,
      (alert) => ({
        title: "人格文件已变更",
        body: `${alert.path} 已与已批准基线不一致。`,
      }),
    );
    expect(merged[0]).toMatchObject({
      alertId: "alert-1",
      inboxEventId: "evt-1",
      title: "人格文件已变更",
      body: "SOUL.md 已与已批准基线不一致。",
    });
  });
});
