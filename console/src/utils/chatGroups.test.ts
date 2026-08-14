import { describe, expect, it } from "vitest";
import type { ChatGroup } from "../api/types/chat";
import {
  groupChats,
  groupChatsByDate,
  resolveChatGroupId,
  SUBAGENT_GROUP_ID,
} from "./chatGroups";

const groups: ChatGroup[] = [
  {
    id: "default",
    name: "Uncategorized",
    order: 0,
    kind: "default",
    pinned: false,
  },
  {
    id: "subagents",
    name: "Subagents",
    order: 1,
    kind: "subagents",
    pinned: false,
  },
  {
    id: "work",
    name: "Work",
    order: 2,
    kind: "custom",
    pinned: true,
  },
];

describe("chatGroups", () => {
  it("places an unassigned subagent in the built-in subagent group", () => {
    expect(resolveChatGroupId({ source: "subagent" })).toBe(SUBAGENT_GROUP_ID);
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
        { id: "worker", source: "subagent" as const },
        { id: "moved", source: "subagent" as const, groupId: "work" },
      ],
      groups,
    );

    expect(result.map((item) => item.group.id)).toEqual([
      "work",
      "default",
      "subagents",
    ]);
    expect(result[0].sessions.map((session) => session.id)).toEqual(["moved"]);
    expect(result[2].sessions.map((session) => session.id)).toEqual(["worker"]);
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
