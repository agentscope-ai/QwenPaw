import { describe, expect, it } from "vitest";
import type { ChatGroup } from "../api/types/chat";
import {
  groupChats,
  groupChatsByDate,
  findStickyGroupHeaderIndex,
  CRON_GROUP_ID,
  resolveChatGroupId,
  SUBAGENT_GROUP_ID,
} from "./chatGroups";

const groups: ChatGroup[] = [
  {
    id: "default",
    name: "Uncategorized",
    order: 0,
    kind: "default",
    source: "chat",
    pinned: false,
  },
  {
    id: "cron",
    name: "Scheduled tasks",
    order: 1,
    kind: "cron",
    source: "cron",
    pinned: false,
  },
  {
    id: "subagents",
    name: "Subagents",
    order: 2,
    kind: "subagents",
    source: "subagent",
    pinned: false,
  },
  {
    id: "work",
    name: "Work",
    order: 3,
    kind: "custom",
    pinned: true,
  },
];

describe("chatGroups", () => {
  it("places an unassigned subagent in the built-in subagent group", () => {
    expect(resolveChatGroupId({ source: "subagent" })).toBe(SUBAGENT_GROUP_ID);
  });

  it("places an unassigned cron chat in the built-in cron group", () => {
    expect(resolveChatGroupId({ source: "cron" })).toBe(CRON_GROUP_ID);
  });

  it("keeps subagent identity while allowing a custom group", () => {
    expect(resolveChatGroupId({ source: "subagent", groupId: "work" })).toBe(
      "work",
    );
  });

  it("pins groups while keeping the Subagents group last", () => {
    const result = groupChats(
      [
        { id: "regular", source: "chat" as const },
        { id: "scheduled", source: "cron" as const },
        { id: "worker", source: "subagent" as const },
        { id: "moved", source: "subagent" as const, groupId: "work" },
      ],
      groups,
    );

    expect(result.map((item) => item.group.id)).toEqual([
      "work",
      "default",
      "cron",
      "subagents",
    ]);
    expect(result[0].sessions.map((session) => session.id)).toEqual(["moved"]);
    expect(result[2].sessions.map((session) => session.id)).toEqual([
      "scheduled",
    ]);
    expect(result[3].sessions.map((session) => session.id)).toEqual(["worker"]);
  });

  it("falls back to the source group when a group no longer exists", () => {
    const result = groupChats(
      [
        { id: "regular", source: "chat" as const, groupId: "deleted" },
        {
          id: "worker",
          source: "subagent" as const,
          groupId: "deleted",
        },
      ],
      groups,
    );

    expect(result[1].sessions.map((session) => session.id)).toEqual([
      "regular",
    ]);
    expect(result[3].sessions.map((session) => session.id)).toEqual(["worker"]);
  });

  it("places pinned conversations before date sections inside a group", () => {
    const result = groupChatsByDate([
      { id: "recent", updatedAt: new Date().toISOString() },
      {
        id: "pinned-old",
        pinned: true,
        updatedAt: "2000-01-01T00:00:00.000Z",
      },
    ]);

    expect(result.map((item) => item.key)).toEqual(["pinned", "today"]);
    expect(result[0].sessions[0].id).toBe("pinned-old");
  });

  it("keeps the current group toggle visible inside a long group", () => {
    const rows = [
      { kind: "groupHeader" },
      { kind: "dateHeader" },
      { kind: "session" },
      { kind: "groupHeader" },
    ];

    expect(findStickyGroupHeaderIndex(rows, 0)).toBeNull();
    expect(findStickyGroupHeaderIndex(rows, 2)).toBe(0);
    expect(findStickyGroupHeaderIndex(rows, 3)).toBeNull();
  });

  it("keeps date sections inside each business group", () => {
    const result = groupChatsByDate([
      { id: "recent", updatedAt: new Date().toISOString() },
      { id: "old", updatedAt: "2000-01-01T00:00:00.000Z" },
    ]);

    expect(result.map((item) => item.key)).toEqual(["today", "older"]);
    expect(result[0].sessions[0].id).toBe("recent");
    expect(result[1].sessions[0].id).toBe("old");
  });
});
