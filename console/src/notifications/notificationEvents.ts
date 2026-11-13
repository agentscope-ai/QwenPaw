import type { NotificationPreferences } from "./preferences";

export interface SystemNotificationEvent {
  id: string;
  category: "conversation" | "cron" | "heartbeat" | "mail";
  agent_id: string;
  title: string;
  body: string;
  created_at: number;
  session_id?: string | null;
  inbox_event_id?: string | null;
}

export function shouldNotifyEvent(
  event: SystemNotificationEvent,
  preferences: NotificationPreferences,
  background: boolean,
): boolean {
  if (!preferences.enabled) return false;
  if (event.category === "conversation")
    return (
      preferences.conversation === "always" ||
      (preferences.conversation === "background" && background)
    );
  return background && preferences[event.category] === true;
}

export function notificationEventPath(event: SystemNotificationEvent): string {
  if (event.category === "conversation" && event.session_id) {
    return `/chat/${encodeURIComponent(
      event.session_id,
    )}?agent=${encodeURIComponent(event.agent_id)}`;
  }
  const query = new URLSearchParams({ tab: "messages" });
  if (event.inbox_event_id) query.set("event", event.inbox_event_id);
  return `/inbox?${query}`;
}
