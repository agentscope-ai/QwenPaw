import { afterEach, describe, expect, it, vi } from "vitest";
import type { ChatHistory } from "../../api/types";
import { chatApi } from "../../api/modules/chat";
import {
  prefetchChatHistory,
  takeChatHistoryPrefetch,
} from "./chatRoutePrefetch";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("cold-route history prefetch", () => {
  it("shares the matching request exactly once", async () => {
    const history = { messages: [], status: "idle" } as ChatHistory;
    const request = vi.spyOn(chatApi, "getChat").mockResolvedValue(history);
    const controller = new AbortController();

    prefetchChatHistory("chat-share", "agent-a", controller.signal);
    prefetchChatHistory("chat-share", "agent-a", controller.signal);

    await expect(
      takeChatHistoryPrefetch("chat-share", "agent-a"),
    ).resolves.toBe(history);
    expect(request).toHaveBeenCalledOnce();
    expect(request).toHaveBeenCalledWith("chat-share", {
      signal: controller.signal,
      agentId: "agent-a",
      include_app_owned: false,
    });
    expect(takeChatHistoryPrefetch("chat-share", "agent-a")).toBeNull();
  });

  it("drops an aborted request before a later route visit", () => {
    const request = vi
      .spyOn(chatApi, "getChat")
      .mockReturnValue(new Promise<ChatHistory>(() => undefined));
    const first = new AbortController();
    const second = new AbortController();

    prefetchChatHistory("chat-abort", "agent-a", first.signal);
    first.abort();
    prefetchChatHistory("chat-abort", "agent-a", second.signal);

    expect(request).toHaveBeenCalledTimes(2);
  });
});
