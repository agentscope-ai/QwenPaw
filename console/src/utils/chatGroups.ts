import type { ChatGroup } from "../api/types/chat";
import { getDateGroup } from "./sessionGrouping";

export const DEFAULT_GROUP_ID = "default";
export const CRON_GROUP_ID = "cron";
export const SUBAGENT_GROUP_ID = "subagents";
export type ChatDateGroup = "pinned" | "today" | "week" | "month" | "older";

export interface GroupedChats<T> {
  group: ChatGroup;
  sessions: T[];
}

interface GroupableChat {
  source?: "chat" | "cron" | "subagent";
  groupId?: string | null;
  pinned?: boolean;
  updatedAt?: string | null;
  createdAt?: string | null;
}

function resolveSourceGroupId(chat: GroupableChat): string {
  if (chat.source === "cron") return CRON_GROUP_ID;
  if (chat.source === "subagent") return SUBAGENT_GROUP_ID;
  return DEFAULT_GROUP_ID;
}

export function resolveChatGroupId(chat: GroupableChat): string {
  if (chat.groupId) return chat.groupId;
  return resolveSourceGroupId(chat);
}

export function localizeSystemGroups(
  groups: ChatGroup[],
  labels: { default: string; cron: string; subagents: string },
): ChatGroup[] {
  return groups.map((group) => {
    if (group.kind === "default" && group.name === "Uncategorized") {
      return { ...group, name: labels.default };
    }
    if (group.kind === "cron") {
      return { ...group, name: labels.cron };
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
  const groupIds = new Set(groups.map((group) => group.id));

  for (const session of sessions) {
    const resolvedGroupId = resolveChatGroupId(session);
    const groupId = groupIds.has(resolvedGroupId)
      ? resolvedGroupId
      : resolveSourceGroupId(session);
    const bucket = buckets.get(groupId) ?? [];
    bucket.push(session);
    buckets.set(groupId, bucket);
  }

  const result: GroupedChats<T>[] = [];
  const orderedGroups = [...groups].sort(
    (a, b) =>
      Number(a.kind === "cron" || a.kind === "subagents") -
        Number(b.kind === "cron" || b.kind === "subagents") ||
      (a.kind !== "custom" && b.kind !== "custom"
        ? Number(a.kind === "subagents") - Number(b.kind === "subagents")
        : 0) ||
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
    pinned: [],
    today: [],
    week: [],
    month: [],
    older: [],
  };
  for (const session of sessions) {
    const key = session.pinned
      ? "pinned"
      : getDateGroup(session.updatedAt ?? session.createdAt);
    buckets[key].push(session);
  }
  return (["pinned", "today", "week", "month", "older"] as const)
    .filter((key) => buckets[key].length > 0)
    .map((key) => ({ key, sessions: buckets[key] }));
}

export function findStickyGroupHeaderIndex(
  rows: Array<{ kind: string }>,
  visibleStartIndex: number,
): number | null {
  for (
    let index = Math.min(visibleStartIndex, rows.length - 1);
    index >= 0;
    index -= 1
  ) {
    if (rows[index].kind !== "groupHeader") continue;
    return index === visibleStartIndex ? null : index;
  }
  return null;
}
