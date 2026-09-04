import type { ChatGroup, ChatSpec, Connection } from "../../api/types";
import {
  type ChatActivityMap,
  resolveChatActivity,
} from "../../storage/chatActivityModel";

export interface ChatSection {
  key: string;
  title: string;
  data: ChatSpec[];
  pinned?: boolean;
  group?: ChatGroup;
}

export function buildChatSections(
  chats: ChatSpec[],
  groups: ChatGroup[],
  pinnedChatId: string | null,
  connection: Connection | null = null,
  activity: ChatActivityMap = {},
): ChatSection[] {
  const pinned = pinnedChatId
    ? chats.filter((chat) => chat.id === pinnedChatId)
    : [];
  const remaining = chats.filter((chat) => chat.id !== pinnedChatId);
  const sections: ChatSection[] = pinned.length
    ? [{ key: "pinned", title: "置顶", data: pinned, pinned: true }]
    : [];

  const orderedGroups = [...groups].sort((left, right) => left.order - right.order);
  for (const group of orderedGroups) {
    const data = sortChatsByAttention(
      remaining.filter((chat) => group.kind === "default"
        ? !chat.group_id || chat.group_id === group.id
        : chat.group_id === group.id),
      connection,
      activity,
    );
    sections.push({
      key: group.id,
      title: groupTitle(group),
      data,
      group,
    });
  }
  const knownIds = new Set(groups.map((group) => group.id));
  const hasDefaultGroup = groups.some((group) => group.kind === "default");
  const ungrouped = remaining.filter(
    (chat) => (!chat.group_id && !hasDefaultGroup) ||
      Boolean(chat.group_id && !knownIds.has(chat.group_id)),
  );
  if (ungrouped.length || !hasDefaultGroup) {
    sections.push({
      key: "ungrouped",
      title: "未分组",
      data: sortChatsByAttention(ungrouped, connection, activity),
    });
  }
  return sections;
}

export function sortChatsByAttention(
  chats: ChatSpec[],
  connection: Connection | null,
  activity: ChatActivityMap,
): ChatSpec[] {
  return chats.map((chat, index) => ({ chat, index })).sort((left, right) => {
    const priority = activityPriority(
      resolveChatActivity(connection, left.chat, activity),
    ) - activityPriority(
      resolveChatActivity(connection, right.chat, activity),
    );
    if (priority) return priority;
    const recency = chatTimestamp(right.chat) - chatTimestamp(left.chat);
    return recency || left.index - right.index;
  }).map(({ chat }) => chat);
}

function activityPriority(activity: string): number {
  if (activity === "running") return 0;
  if (activity === "unread") return 1;
  return 2;
}

function chatTimestamp(chat: ChatSpec): number {
  const value = chat.updated_at ?? chat.created_at;
  if (!value) return 0;
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? timestamp : 0;
}

function groupTitle(group: ChatGroup): string {
  if (group.kind === "default") return "未分组";
  if (group.kind === "cron") return "定时任务";
  if (group.kind === "subagents") return "子智能体";
  return group.name;
}
