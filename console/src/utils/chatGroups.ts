import type { ChatGroup } from "../api/types/chat";

export const PINNED_GROUP_ID = "__pinned__";
export const DEFAULT_GROUP_ID = "default";
export const SUBAGENT_GROUP_ID = "subagents";

export interface GroupedChats<T> {
  group: ChatGroup;
  sessions: T[];
  pinned: boolean;
}

interface GroupableChat {
  pinned?: boolean;
  source?: "chat" | "cron" | "subagent";
  groupId?: string | null;
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
    if (group.kind === "subagents" && group.name === "Subagents") {
      return { ...group, name: labels.subagents };
    }
    return group;
  });
}

export function groupChats<T extends GroupableChat>(
  sessions: T[],
  groups: ChatGroup[],
  pinnedLabel: string,
): GroupedChats<T>[] {
  const pinned = sessions.filter((session) => session.pinned);
  const regular = sessions.filter((session) => !session.pinned);
  const buckets = new Map<string, T[]>();

  for (const session of regular) {
    const groupId = resolveChatGroupId(session);
    const bucket = buckets.get(groupId) ?? [];
    bucket.push(session);
    buckets.set(groupId, bucket);
  }

  const result: GroupedChats<T>[] = [];
  if (pinned.length > 0) {
    result.push({
      group: {
        id: PINNED_GROUP_ID,
        name: pinnedLabel,
        order: -1,
        kind: "custom",
      },
      sessions: pinned,
      pinned: true,
    });
  }

  for (const group of [...groups].sort((a, b) => a.order - b.order)) {
    result.push({
      group,
      sessions: buckets.get(group.id) ?? [],
      pinned: false,
    });
  }

  return result;
}
