import type { InboxEvent } from "@/api/modules/console";
import type { FileBaselineProtectionAlert } from "../api/client";

export interface FileBaselineDriftAlertItem {
  alertId: string;
  inboxEventId?: string;
  path: string;
  title: string;
  body: string;
  provenance: string;
}

export interface FileBaselineDriftAlertCopy {
  title: string;
  body: string;
}

export function mapInboxEventsByAlertId(
  events: InboxEvent[],
): Map<string, InboxEvent> {
  const byAlertId = new Map<string, InboxEvent>();
  for (const event of events) {
    if ((event.event_type || "").toLowerCase() !== "file_baseline_drift") {
      continue;
    }
    const alertId =
      event.source_id ||
      (typeof event.payload?.alert_id === "string"
        ? event.payload.alert_id
        : "");
    if (alertId) {
      byAlertId.set(alertId, event);
    }
  }
  return byAlertId;
}

export function mergeAlertItems(
  openAlerts: FileBaselineProtectionAlert[],
  inboxByAlertId: Map<string, InboxEvent>,
  localize: (alert: FileBaselineProtectionAlert) => FileBaselineDriftAlertCopy,
): FileBaselineDriftAlertItem[] {
  return openAlerts.map((alert) => {
    const inboxEvent = inboxByAlertId.get(alert.alert_id);
    const { title, body } = localize(alert);
    return {
      alertId: alert.alert_id,
      inboxEventId: inboxEvent?.id,
      path: alert.path,
      title,
      body,
      provenance: alert.provenance,
    };
  });
}
