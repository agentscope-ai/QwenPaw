import { describe, expect, it } from "vitest";
import {
  resolveRuntimeChatId,
  resolveSessionInitializerChatId,
} from "../agentSwitchScope";

describe("resolveRuntimeChatId", () => {
  it("keeps the destination chat paired with the destination agent while routing", () => {
    expect(
      resolveRuntimeChatId("agent-1-chat", "agent-2", {
        agentId: "agent-2",
        chatId: "agent-2-chat",
      }),
    ).toBe("agent-2-chat");
  });

  it("suppresses the previous route when the destination agent has no chat", () => {
    expect(
      resolveRuntimeChatId("agent-1-chat", "agent-2", {
        agentId: "agent-2",
      }),
    ).toBeUndefined();
  });

  it("uses the current route outside the pending agent scope", () => {
    expect(
      resolveRuntimeChatId("agent-1-chat", "agent-1", {
        agentId: "agent-2",
        chatId: "agent-2-chat",
      }),
    ).toBe("agent-1-chat");
  });

  it("keeps the session initializer blank while a new chat is being created", () => {
    expect(
      resolveSessionInitializerChatId(
        "previous-chat",
        "agent-2",
        { agentId: "agent-2", chatId: "restored-chat" },
        true,
      ),
    ).toBeUndefined();
  });
});
