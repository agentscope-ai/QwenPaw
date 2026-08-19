import type { InboxEvent } from "../api/modules/console";

export const INBOX_EVENT_QUERY_LIMIT = 200;

export const PUSH_MESSAGE_SOURCES = [
  "cron",
  "heartbeat",
  "memory",
  "skill_autoupdate",
] as const;

const PUSH_MESSAGE_SOURCE_SET = new Set<string>(PUSH_MESSAGE_SOURCES);

export function isPushMessageEvent(event: InboxEvent): boolean {
  return PUSH_MESSAGE_SOURCE_SET.has(event.source_type);
}
