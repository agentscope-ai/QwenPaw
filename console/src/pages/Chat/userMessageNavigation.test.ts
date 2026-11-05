import { describe, expect, it } from "vitest";
import type { IAgentScopeRuntimeWebUIMessage } from "@agentscope-ai/chat";
import {
  activeUserAtScrollPosition,
  getNavigationUsers,
  mergeNavigationUsers,
} from "./userMessageNavigation";

const entry = (messageId: string, clientMessageId?: string) => ({
  messageId,
  clientMessageId,
  preview: "same input",
  createdAt: "",
  anchor: "cursor",
});

describe("Chat user directory", () => {
  it("selects the final loaded user at the bottom of a long assistant reply", () => {
    expect(
      activeUserAtScrollPosition(
        [
          { id: "first", top: -4000 },
          { id: "last", top: -2000 },
        ],
        70,
        true,
      ),
    ).toBe("last");
  });

  it("tracks the containing turn in both directions, not the next input", () => {
    const users = [
      { id: "second", top: 300 },
      { id: "first", top: -100 },
    ];
    expect(activeUserAtScrollPosition(users, 70, false)).toBe("first");
    expect(activeUserAtScrollPosition(users, 324, false)).toBe("second");
    expect(activeUserAtScrollPosition(users, 70, false)).toBe("first");
    expect(activeUserAtScrollPosition([], 70, true)).toBeUndefined();
  });

  it("keeps all persisted users when only the latest page is visible", () => {
    const persisted = Array.from({ length: 49 }, (_, i) => entry(`user-${i}`));
    expect(mergeNavigationUsers(persisted, persisted.slice(-5))).toEqual(
      persisted,
    );
  });

  it("adds an optimistic input immediately and counts it once after persistence", () => {
    const live = entry("client-2");
    expect(mergeNavigationUsers([entry("user-1")], [live])).toHaveLength(2);
    const persisted = [entry("user-1"), entry("server-2", "client-2")];
    expect(mergeNavigationUsers(persisted, [live])).toEqual(persisted);
  });

  it("deduplicates client metadata aliases but not repeated text", () => {
    const persisted = [entry("server-1", "client-1")];
    expect(
      mergeNavigationUsers(persisted, [
        entry("sdk-1", "client-1"),
        entry("sdk-2"),
      ]),
    ).toHaveLength(2);
  });

  it("ignores assistant streaming updates and bounds previews", () => {
    const user = {
      id: "user-1",
      role: "user",
      cards: [
        {
          code: "AgentScopeRuntimeRequestCard",
          data: {
            created_at: 1700000000,
            input: [
              {
                metadata: { qwenpaw_client_message_id: "client-1" },
                content: [{ text: "a".repeat(1000) }],
              },
            ],
          },
        },
      ],
    } as IAgentScopeRuntimeWebUIMessage;
    const users = getNavigationUsers([user]);
    expect(users[0].preview).toHaveLength(160);
    expect(users[0].clientMessageId).toBe("client-1");
    expect(
      getNavigationUsers([
        user,
        { id: "assistant", role: "assistant", cards: [] },
      ]),
    ).toEqual(users);
  });
});
