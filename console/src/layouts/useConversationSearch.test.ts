// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { chatApi } from "../api/modules/chat";
import type { ChatSearchResponse } from "../api/types/chat";
import { useConversationSearch } from "./useConversationSearch";

vi.mock("../api/modules/chat", () => ({ chatApi: { searchChats: vi.fn() } }));

function response(
  query: string,
  ids = ["chat-1"],
  hasMore = false,
): ChatSearchResponse {
  return {
    query,
    mode: "keyword",
    total: hasMore ? 40 : ids.length,
    has_more: hasMore,
    partial: false,
    queries: [query],
    results: ids.map((id) => ({
      chat: {
        id,
        name: id,
        session_id: id,
        user_id: "user",
        channel: "console",
        created_at: null,
        updated_at: null,
      },
      snippet: query,
      role: "user",
    })),
  };
}

async function advance(ms = 275) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe("useConversationSearch", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(chatApi.searchChats)
      .mockReset()
      .mockImplementation(async ({ query }) => response(query));
  });
  afterEach(() => vi.useRealTimers());

  it("debounces keywords and scopes the request to the active agent", async () => {
    const { result } = renderHook(() => useConversationSearch("agent-1"));
    act(() => result.current.setQuery("deploy"));
    await advance(200);
    act(() => result.current.setQuery(" deployment "));
    await advance(274);
    expect(chatApi.searchChats).not.toHaveBeenCalled();
    await advance(1);
    expect(chatApi.searchChats).toHaveBeenCalledExactlyOnceWith(
      { query: "deployment", mode: "keyword", limit: 20, offset: 0 },
      { agentId: "agent-1", signal: expect.any(AbortSignal) },
    );
    expect(result.current.response?.results).toHaveLength(1);
  });

  it("requires explicit AI submission and cancels keyword requests when switching mode", async () => {
    const { result } = renderHook(() => useConversationSearch("agent-1"));
    act(() => result.current.setQuery("deployment"));
    await advance();
    const signal = vi.mocked(chatApi.searchChats).mock.calls[0][1].signal!;
    act(() => result.current.setMode("agent"));
    expect(signal.aborted).toBe(true);
    expect(result.current.response).toBeNull();
    expect(result.current.awaitingSubmit).toBe(true);
    await advance(1000);
    expect(chatApi.searchChats).toHaveBeenCalledTimes(1);
    act(() => result.current.submit());
    await advance(0);
    expect(chatApi.searchChats).toHaveBeenLastCalledWith(
      expect.objectContaining({ mode: "agent", query: "deployment" }),
      expect.anything(),
    );
    act(() => result.current.setQuery("production deployment"));
    await advance(1000);
    expect(chatApi.searchChats).toHaveBeenCalledTimes(2);
    expect(result.current.response).toBeNull();
  });

  it("ignores late results after a query change even if the transport ignores abort", async () => {
    let resolveOld!: (value: ChatSearchResponse) => void;
    vi.mocked(chatApi.searchChats).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveOld = resolve;
        }),
    );
    const { result } = renderHook(() => useConversationSearch("agent-1"));
    act(() => result.current.setQuery("old"));
    await advance();
    const signal = vi.mocked(chatApi.searchChats).mock.calls[0][1].signal!;
    act(() => result.current.setQuery("new"));
    expect(signal.aborted).toBe(true);
    await advance();
    await act(async () => {
      resolveOld(response("old"));
    });
    expect(result.current.response?.query).toBe("new");
    act(() => result.current.setQuery(""));
    expect(result.current.active).toBe(false);
    expect(result.current.response).toBeNull();
  });

  it("resets input and mode on agent switch and suppresses previous agent responses", async () => {
    let resolveOld!: (value: ChatSearchResponse) => void;
    vi.mocked(chatApi.searchChats).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveOld = resolve;
        }),
    );
    const { result, rerender } = renderHook(
      ({ agentId }) => useConversationSearch(agentId),
      { initialProps: { agentId: "agent-1" } },
    );
    act(() => result.current.setMode("agent"));
    act(() => result.current.setQuery("deployment"));
    act(() => result.current.submit());
    await advance(0);
    const signal = vi.mocked(chatApi.searchChats).mock.calls[0][1].signal!;
    rerender({ agentId: "agent-2" });
    expect(result.current.query).toBe("");
    expect(result.current.mode).toBe("keyword");
    expect(signal.aborted).toBe(true);
    await act(async () => {
      resolveOld(response("deployment"));
    });
    expect(result.current.response).toBeNull();
    expect(result.current.loading).toBe(false);
  });

  it("rejects an old response when returning to the same query after mode changes", async () => {
    let resolveOld!: (value: ChatSearchResponse) => void;
    vi.mocked(chatApi.searchChats).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveOld = resolve;
        }),
    );
    const { result } = renderHook(() => useConversationSearch("agent-1"));
    act(() => result.current.setQuery("deploy"));
    await advance();
    act(() => result.current.setMode("agent"));
    act(() => result.current.setMode("keyword"));
    await advance();
    expect(result.current.response?.results[0].chat.id).toBe("chat-1");
    await act(async () => {
      resolveOld(response("deploy", ["stale-chat"]));
    });
    expect(result.current.response?.results[0].chat.id).toBe("chat-1");
  });

  it("appends pages, keeps results on pagination failure, and retries the same offset", async () => {
    const firstIds = Array.from({ length: 20 }, (_, index) => `chat-${index}`);
    vi.mocked(chatApi.searchChats)
      .mockResolvedValueOnce(response("deploy", firstIds, true))
      .mockRejectedValueOnce(new Error("network"))
      .mockResolvedValueOnce(response("deploy", ["chat-19", "chat-20"], true))
      .mockResolvedValueOnce(response("deploy", ["chat-21"]));
    const { result } = renderHook(() => useConversationSearch("agent-1"));
    act(() => result.current.setQuery("deploy"));
    await advance();
    await act(async () => result.current.loadMore());
    expect(result.current.error).toBe(true);
    expect(result.current.response?.results).toHaveLength(20);
    await act(async () => result.current.loadMore());
    expect(result.current.error).toBe(false);
    expect(result.current.response?.results).toHaveLength(21);
    await act(async () => result.current.loadMore());
    expect(
      vi
        .mocked(chatApi.searchChats)
        .mock.calls.map(([request]) => request.offset),
    ).toEqual([0, 20, 20, 22]);
    expect(result.current.response?.has_more).toBe(false);
  });

  it("can retry a failed search and aborts on unmount", async () => {
    vi.mocked(chatApi.searchChats).mockRejectedValueOnce(new Error("offline"));
    const { result, unmount } = renderHook(() =>
      useConversationSearch("agent-1"),
    );
    act(() => result.current.setQuery("deploy"));
    await advance();
    expect(result.current.error).toBe(true);
    act(() => result.current.submit());
    await advance();
    expect(result.current.error).toBe(false);
    const signal = vi.mocked(chatApi.searchChats).mock.calls[1][1].signal!;
    unmount();
    expect(signal.aborted).toBe(true);
  });
});
