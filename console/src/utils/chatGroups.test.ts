import { describe, expect, it } from "vitest";
import type { ChatGroup } from "../api/types/chat";
import {
  groupChats,
  resolveChatGroupId,
  SUBAGENT_GROUP_ID,
} from "./chatGroups";

const groups: ChatGroup[] = [
  { id: "default", name: "Uncategorized", order: 0, kind: "default" },
  { id: "subagents", name: "Subagents", order: 1, kind: "subagents" },
  { id: "work", name: "Work", order: 2, kind: "custom" },
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

  it("groups pinned chats separately and follows persisted group order", () => {
    const result = groupChats(
      [
        { id: "pinned", pinned: true, source: "chat" as const },
        { id: "worker", source: "subagent" as const },
        { id: "moved", source: "subagent" as const, groupId: "work" },
      ],
      groups,
      "Pinned",
    );

    expect(result.map((item) => item.group.id)).toEqual([
      "__pinned__",
      "default",
      "subagents",
      "work",
    ]);
    expect(result[2].sessions.map((session) => session.id)).toEqual(["worker"]);
    expect(result[3].sessions.map((session) => session.id)).toEqual(["moved"]);
  });
});
