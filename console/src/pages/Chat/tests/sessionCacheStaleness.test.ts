/**
 * Regression test for issue #6131 follow-up:
 * "Messages sent from an external channel (DingTalk) don't appear in the
 *  console conversation; switching away and back doesn't help — only a full
 *  page refresh shows them."
 *
 * Root cause: SessionApi keeps an in-memory LRU cache of converted messages
 * keyed by backend UUID. On session switch-back, `fetchAndBuildSession`
 * returned the cached messages for idle chats WITHOUT re-fetching. The cache
 * was only invalidated when the LOCAL user sent a message — never when a
 * message arrived from an external channel. A full page refresh worked only
 * because it recreates the SessionApi singleton (empty cache).
 *
 * Fix: the cache entry now records the chat's backend `updated_at`; on read we
 * compare it against the freshly-polled `updated_at` from the session list and
 * treat the entry as stale (re-fetch) when the backend is newer.
 *
 * These tests drive the public `getSession` / `getSessionList` flow with
 * mocked `api.getChat` / `api.listChats`, asserting a re-fetch happens exactly
 * when `updated_at` advances (and NOT when it stays the same).
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import type { ChatSpec, ChatHistory, Message } from "../../../api";
import api from "../../../api";
import sessionApi from "../sessionApi";

const T0 = "2026-07-16T15:30:00.000000+00:00";
const T1 = "2026-07-16T15:36:00.000000+00:00";

function makeChatSpec(id: string, updatedAt: string): ChatSpec {
  return {
    id,
    name: "DingTalk chat",
    session_id: `dingtalk:${id}`,
    user_id: "u1",
    channel: "dingtalk",
    created_at: T0,
    updated_at: updatedAt,
    meta: {},
    status: "idle",
    pinned: false,
    archived: false,
    archived_at: null,
  } as unknown as ChatSpec;
}

function makeHistory(
  turns: Array<{ role: string; text: string }>,
): ChatHistory {
  const messages: Message[] = turns.map(
    ({ role, text }) =>
      ({
        role,
        content: [{ type: "text", text }],
      }) as unknown as Message,
  );
  return { messages, status: "idle" } as unknown as ChatHistory;
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("SessionApi converted-cache staleness on updated_at change (#6131)", () => {
  it("re-fetches messages when the backend updated_at advances", async () => {
    const id = "11111111-1111-4111-8111-111111111111";
    const listSpy = vi
      .spyOn(api, "listChats")
      .mockResolvedValue([makeChatSpec(id, T0)]);
    const getChatSpy = vi
      .spyOn(api, "getChat")
      .mockResolvedValue(makeHistory([{ role: "assistant", text: "first" }]));

    // Initial poll + open: fetches history v1 and caches it.
    await sessionApi.getSessionList();
    const s1 = await sessionApi.getSession(id);
    expect(getChatSpy).toHaveBeenCalledTimes(1);
    const count1 = (s1.messages || []).length;

    // A new message arrives via DingTalk: backend updated_at advances and the
    // history now has an extra user turn + reply (distinct cards).
    listSpy.mockResolvedValue([makeChatSpec(id, T1)]);
    getChatSpy.mockResolvedValue(
      makeHistory([
        { role: "assistant", text: "first" },
        { role: "user", text: "what time is it" },
        { role: "assistant", text: "second" },
      ]),
    );

    // Poll picks up the newer updated_at, then the user switches back.
    await sessionApi.getSessionList();
    const s2 = await sessionApi.getSession(id);

    // Must have re-fetched (cache treated as stale) and show the new message.
    expect(getChatSpy).toHaveBeenCalledTimes(2);
    expect((s2.messages || []).length).toBeGreaterThan(count1);
  });

  it("serves the cache (no re-fetch) when updated_at is unchanged", async () => {
    const id = "22222222-2222-4222-8222-222222222222";
    vi.spyOn(api, "listChats").mockResolvedValue([makeChatSpec(id, T0)]);
    const getChatSpy = vi
      .spyOn(api, "getChat")
      .mockResolvedValue(makeHistory([{ role: "assistant", text: "only" }]));

    await sessionApi.getSessionList();
    await sessionApi.getSession(id);
    expect(getChatSpy).toHaveBeenCalledTimes(1);

    // Poll again with the SAME updated_at, then switch back.
    await sessionApi.getSessionList();
    await sessionApi.getSession(id);

    // Cache is still valid: no extra network fetch.
    expect(getChatSpy).toHaveBeenCalledTimes(1);
  });
});
