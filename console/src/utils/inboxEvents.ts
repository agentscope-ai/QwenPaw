import type { InboxEvent } from "../api/modules/console";

export const INBOX_EVENT_QUERY_LIMIT = 200;

export const PUSH_MESSAGE_SOURCES = [
  "cron",
  "heartbeat",
  "memory",
  "skill_autoupdate",
  "mail",
  "community",
] as const;

export const INBOX_CHANGED_EVENT = "qwenpaw:inbox-changed";
export const INBOX_OPEN_EVENT = "qwenpaw:inbox-open";
export const INBOX_SOURCE_STORAGE_KEY = "qwenpaw.inbox.sourceType";

export interface InboxChange {
  readIds?: string[];
  deletedIds?: string[];
  readAll?: boolean;
  sourceTypes?: string[];
  agentId?: string;
  clearSources?: string[];
}

/** Notify every inbox surface only after a server mutation succeeds. */
export function notifyInboxChanged(detail: InboxChange = {}): void {
  window.dispatchEvent(new CustomEvent(INBOX_CHANGED_EVENT, { detail }));
}

const PUSH_MESSAGE_SOURCE_SET = new Set<string>(PUSH_MESSAGE_SOURCES);

export function isPushMessageEvent(event: InboxEvent): boolean {
  return PUSH_MESSAGE_SOURCE_SET.has(event.source_type);
}
