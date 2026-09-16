import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { chatApi } from "../../../api/modules/chat";
import { useSharedConversationAccessGuard } from "./useSharedConversationAccessGuard";

vi.mock("../../../api/modules/chat", () => ({
  chatApi: {
    getChat: vi.fn(),
  },
}));

describe("useSharedConversationAccessGuard", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(chatApi.getChat).mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("撤销共享权限后立即通知页面清理只读会话", async () => {
    const onRevoked = vi.fn();
    vi.mocked(chatApi.getChat).mockRejectedValue(
      new Error('not_found - {"detail":"Chat not found"}'),
    );

    renderHook(() =>
      useSharedConversationAccessGuard({
        conversationId: "shared-chat",
        enabled: true,
        intervalMs: 3000,
        onRevoked,
      }),
    );

    await act(async () => {
      await vi.runOnlyPendingTimersAsync();
    });

    expect(chatApi.getChat).toHaveBeenCalledWith("shared-chat");
    expect(onRevoked).toHaveBeenCalledTimes(1);
  });

  it("临时网络错误不会误判为权限撤销", async () => {
    const onRevoked = vi.fn();
    vi.mocked(chatApi.getChat).mockRejectedValue(new Error("Failed to fetch"));

    renderHook(() =>
      useSharedConversationAccessGuard({
        conversationId: "shared-chat",
        enabled: true,
        intervalMs: 3000,
        onRevoked,
      }),
    );

    await act(async () => {
      await vi.runOnlyPendingTimersAsync();
    });

    expect(onRevoked).not.toHaveBeenCalled();
  });

  it("所有者会话不启动额外的权限轮询", async () => {
    renderHook(() =>
      useSharedConversationAccessGuard({
        conversationId: "owned-chat",
        enabled: false,
        intervalMs: 3000,
        onRevoked: vi.fn(),
      }),
    );

    await act(async () => {
      await vi.runOnlyPendingTimersAsync();
    });

    expect(chatApi.getChat).not.toHaveBeenCalled();
  });
});
