import type { ChatGroup } from "../api/types/chat";
import { getDateGroup } from "./sessionGrouping";

export const DEFAULT_GROUP_ID = "default";
export const SUBAGENT_GROUP_ID = "subagents";
export type ChatDateGroup = "today" | "week" | "month" | "older";

export interface GroupedChats<T> {
  group: ChatGroup;
  sessions: T[];
}

interface GroupableChat {
  source?: "chat" | "cron" | "subagent";
  groupId?: string | null;
  updatedAt?: string | null;
  createdAt?: string | null;
}

export function resolveChatGroupId(chat: GroupableChat): string {
  if (chat.groupId) return chat.groupId;
  return chat.source === "subagent" ? SUBAGENT_GROUP_ID : DEFAULT_GROUP_ID;
}

export function localizeSystemGroups(
  groups: ChatGroup[],
  labels: { default: string; subagents: string },
): ChatGroup[] {
  return groups.map((group) => {
    if (group.kind === "default" && group.name === "Uncategorized") {
      return { ...group, name: labels.default };
    }
    if (group.kind === "subagents") {
      return { ...group, name: labels.subagents };
    }
    return group;
  });
}

export function groupChats<T extends GroupableChat>(
  sessions: T[],
  groups: ChatGroup[],
): GroupedChats<T>[] {
  const buckets = new Map<string, T[]>();

  for (const session of sessions) {
    const groupId = resolveChatGroupId(session);
    const bucket = buckets.get(groupId) ?? [];
    bucket.push(session);
    buckets.set(groupId, bucket);
  }

  const result: GroupedChats<T>[] = [];
  const orderedGroups = [...groups].sort(
    (a, b) =>
      Number(a.kind === "subagents") - Number(b.kind === "subagents") ||
      Number(b.pinned) - Number(a.pinned) ||
      a.order - b.order,
  );
  for (const group of orderedGroups) {
    result.push({
      group,
      sessions: buckets.get(group.id) ?? [],
    });
  }

  return result;
}

export function groupChatsByDate<T extends GroupableChat>(
  sessions: T[],
): Array<{ key: ChatDateGroup; sessions: T[] }> {
  const buckets: Record<ChatDateGroup, T[]> = {
    today: [],
    week: [],
    month: [],
    older: [],
  };
  for (const session of sessions) {
    buckets[getDateGroup(session.updatedAt ?? session.createdAt)].push(session);
  }
  return (["today", "week", "month", "older"] as const)
    .filter((key) => buckets[key].length > 0)
    .map((key) => ({ key, sessions: buckets[key] }));
}
