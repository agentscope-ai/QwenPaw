import type { ChatSpec, Connection } from "../api/types";
import { connectionKey } from "./connectionModel";

export type ChatActivity = "running" | "unread" | "read" | "idle";

export interface ChatActivityRecord {
  observedUpdatedAt: string | null;
  hasWork: boolean;
  unread: boolean;
  wasRunning: boolean;
}

export type ChatActivityMap = Record<string, ChatActivityRecord>;

export function chatActivityKey(
  connection: Connection,
  chatId: string,
): string {
  return `${connectionKey(connection)}:${connection.agentId}:${chatId}`;
}

export function reconcileChatActivity(
  current: ChatActivityMap,
  connection: Connection,
  chats: ChatSpec[],
): ChatActivityMap {
  let next = current;
  for (const chat of chats) {
    const key = chatActivityKey(connection, chat.id);
    const existing = current[key];
    const running = chat.status === "running";
    let record: ChatActivityRecord;
    if (!existing) {
      record = {
        observedUpdatedAt: chat.updated_at ?? null,
        hasWork: running || hasExistingWork(chat),
        unread: false,
        wasRunning: running,
      };
    } else {
      const completed = existing.wasRunning && !running;
      const updatedWhileAway = existing.observedUpdatedAt !== null &&
        isLater(chat.updated_at, existing.observedUpdatedAt) &&
        existing.hasWork && !running;
      record = {
        observedUpdatedAt: chat.updated_at ?? existing.observedUpdatedAt,
        hasWork: existing.hasWork || running || hasExistingWork(chat),
        unread: existing.unread || completed || updatedWhileAway,
        wasRunning: running,
      };
    }
    if (existing && sameRecord(existing, record)) continue;
    if (next === current) next = { ...current };
    next[key] = record;
  }
  return next;
}

function sameRecord(
  left: ChatActivityRecord,
  right: ChatActivityRecord,
): boolean {
  return left.observedUpdatedAt === right.observedUpdatedAt &&
    left.hasWork === right.hasWork &&
    left.unread === right.unread &&
    left.wasRunning === right.wasRunning;
}

export function markActivityRead(
  current: ChatActivityMap,
  connection: Connection,
  chat: ChatSpec,
  hasMessages: boolean,
): ChatActivityMap {
  const key = chatActivityKey(connection, chat.id);
  const record: ChatActivityRecord = {
    observedUpdatedAt: chat.updated_at ?? current[key]?.observedUpdatedAt ?? null,
    hasWork: hasMessages || current[key]?.hasWork || hasExistingWork(chat),
    unread: false,
    wasRunning: chat.status === "running",
  };
  if (current[key] && sameRecord(current[key], record)) return current;
  return {
    ...current,
    [key]: record,
  };
}

export function resolveChatActivity(
  connection: Connection | null,
  chat: ChatSpec,
  activity: ChatActivityMap,
): ChatActivity {
  if (chat.status === "running") return "running";
  if (!connection) return "idle";
  const record = activity[chatActivityKey(connection, chat.id)];
  if (record?.unread) return "unread";
  if (record?.hasWork || hasExistingWork(chat)) return "read";
  return "idle";
}

function hasExistingWork(chat: ChatSpec): boolean {
  const defaultName = !chat.name || chat.name === "New Chat" || chat.name === "新会话";
  if (!defaultName) return true;
  if (!chat.created_at || !chat.updated_at) return false;
  const created = Date.parse(chat.created_at);
  const updated = Date.parse(chat.updated_at);
  return Number.isFinite(created) && Number.isFinite(updated) &&
    updated - created > 2000;
}

function isLater(value: string | null | undefined, baseline: string): boolean {
  if (!value) return false;
  const next = Date.parse(value);
  const previous = Date.parse(baseline);
  return Number.isFinite(next) && Number.isFinite(previous) && next > previous;
}
