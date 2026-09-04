import assert from "node:assert/strict";
import test from "node:test";

import type { ChatGroup, ChatSpec, Connection } from "../../api/types";
import { reconcileChatActivity } from "../../storage/chatActivityModel";
import { buildChatSections, sortChatsByAttention } from "./grouping";

const connection: Connection = {
  baseUrl: "http://127.0.0.1:8088",
  token: "token",
  username: "user",
  agentId: "default",
  source: "private",
};

const chats: ChatSpec[] = [
  { id: "a", session_id: "a", user_id: "mobile", channel: "console", group_id: "work" },
  { id: "b", session_id: "b", user_id: "mobile", channel: "console" },
  { id: "c", session_id: "c", user_id: "mobile", channel: "console", group_id: "work" },
];

const groups: ChatGroup[] = [{
  id: "work",
  name: "工作",
  order: 1,
  kind: "custom",
  pinned: false,
}];

test("buildChatSections separates pinned grouped and ungrouped chats", () => {
  const sections = buildChatSections(chats, groups, "c");

  assert.deepEqual(sections.map((section) => section.title), [
    "置顶",
    "工作",
    "未分组",
  ]);
  assert.deepEqual(sections.map((section) => section.data.map((chat) => chat.id)), [
    ["c"],
    ["a"],
    ["b"],
  ]);
});

test("buildChatSections keeps empty groups visible", () => {
  const sections = buildChatSections([], groups, null);

  assert.deepEqual(sections.map((section) => section.title), [
    "工作",
    "未分组",
  ]);
  assert.deepEqual(sections.map((section) => section.data), [[], []]);
});

test("running and unread chats lead each group before recent idle chats", () => {
  const running: ChatSpec = {
    ...chats[0],
    id: "running",
    status: "running",
    updated_at: "2026-01-01T00:00:00Z",
  };
  const unreadRunning: ChatSpec = {
    ...chats[0],
    id: "unread",
    status: "running",
    updated_at: "2026-01-01T00:01:00Z",
  };
  const first = reconcileChatActivity(
    {},
    connection,
    [running, unreadRunning],
  );
  const unread = {
    ...unreadRunning,
    status: "idle" as const,
    updated_at: "2026-01-01T00:02:00Z",
  };
  const activity = reconcileChatActivity(first, connection, [running, unread]);
  const recentIdle: ChatSpec = {
    ...chats[0],
    id: "recent-idle",
    status: "idle",
    updated_at: "2026-08-01T00:00:00Z",
  };

  assert.deepEqual(
    sortChatsByAttention(
      [recentIdle, unread, running],
      connection,
      activity,
    ).map((chat) => chat.id),
    ["running", "unread", "recent-idle"],
  );
});
