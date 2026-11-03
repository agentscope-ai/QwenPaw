/**
 * Session API creation lifecycle and pure transforms. Regression family:
 * owner-epoch concurrent creation, failure retry and late-result isolation,
 * session id resolution (local timestamp ids must never be used as backend
 * UUIDs — 404 loops) and message-to-card conversion (history replay must
 * preserve roles/timestamps/attachments).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("@agentscope-ai/chat", () => ({}));

import sessionApi, { __test__ as T } from "./index";
import api, { type ChatHistory, type ChatSpec } from "../../../api";
import { chatApi } from "../../../api/modules/chat";
import { createSdkSessionAdapter } from "../sdkSessionAdapter";
import { prefetchChatHistory } from "../chatRoutePrefetch";
import { groupChatsByDate } from "../../../utils/chatGroups";
import type { ExtendedSession } from "../../../stores/sessionListStore";
import { useSessionListStore } from "../../../stores/sessionListStore";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function createdChat(id: string): ChatSpec {
  return {
    id,
    name: id,
    session_id: `runtime-${id}`,
    user_id: "default",
    channel: "console",
    created_at: "2026-09-09T00:00:00Z",
    updated_at: "2026-09-09T00:00:00Z",
    meta: {},
  };
}

describe("running session discovery", () => {
  beforeEach(() => {
    sessionApi.resetForTests();
    sessionApi.setActiveAgent("A");
  });

  afterEach(() => {
    vi.restoreAllMocks();
    sessionApi.resetForTests();
  });

  it("preserves running discovery and confirmed forks across stale lists and owners", async () => {
    const listChats = vi
      .spyOn(api, "listChats")
      .mockResolvedValue([
        { ...createdChat("running-chat"), status: "running" },
      ]);

    await expect(sessionApi.getSessionList()).resolves.toEqual([
      expect.objectContaining({
        id: "running-chat",
        status: "running",
        generating: true,
      }),
    ]);
    const owner = sessionApi.getActiveOwner();
    const stale = deferred<ChatSpec[]>();
    listChats.mockReturnValueOnce(stale.promise);
    const pending = sessionApi.getSessionList();
    const child = { ...createdChat("fork-chat"), name: "Parent (1)" };
    sessionApi.registerForkedChat(child, owner);
    sessionApi.registerForkedChat(child, owner);
    expect(useSessionListStore.getState().sessions.map((s) => s.id)).toEqual([
      "fork-chat",
      "running-chat",
    ]);
    stale.resolve([]);
    await expect(pending).resolves.toEqual([
      expect.objectContaining({ id: "fork-chat", name: "Parent (1)" }),
      expect.objectContaining({ id: "running-chat", generating: true }),
    ]);
    listChats.mockRejectedValueOnce(new Error("offline"));
    await expect(sessionApi.getSessionList()).rejects.toThrow("offline");
    expect(useSessionListStore.getState().sessions[0].id).toBe("fork-chat");
    sessionApi.setActiveAgent("B");
    const before = useSessionListStore.getState().sessions;
    sessionApi.registerForkedChat(createdChat("late-fork"), owner);
    expect(useSessionListStore.getState().sessions).toBe(before);
  });
});

describe("createSession owner-epoch singleflight", () => {
  beforeEach(() => {
    sessionApi.resetForTests();
    sessionApi.setActiveAgent("A");
  });

  afterEach(() => {
    vi.restoreAllMocks();
    sessionApi.resetForTests();
  });

  it("keeps a live usage turn through first-send URL resolution and history loading", async () => {
    const { useTurnUsageStore } = await import("../turnUsageStore");
    sessionApi.setVisibleSession(null);
    vi.spyOn(sessionApi, "getBackendSessionId").mockReturnValue("runtime-one");
    const turn = useTurnUsageStore.getState().beginTurn("A", "runtime-one");
    const live = { usage: { total_tokens: 125 }, context_usage: null };
    useTurnUsageStore.getState().setSnapshotForTurn(live, turn);
    sessionApi.setVisibleSession("one");
    vi.spyOn(api, "getChat").mockResolvedValue({
      messages: [],
      status: "idle",
    } as ChatHistory);
    await sessionApi.getSession("one");
    expect(useTurnUsageStore.getState().activeTurn).toEqual(turn);
    expect(useTurnUsageStore.getState().snapshot).toEqual(live);
    sessionApi.setVisibleSession(null);
    expect(useTurnUsageStore.getState().activeTurn).toBeNull();
  });

  it("reuses cold-route history instead of requesting the Chat twice", async () => {
    const history = {
      messages: [],
      status: "idle",
    } as ChatHistory;
    const prefetched = vi.spyOn(chatApi, "getChat").mockResolvedValue(history);
    const fallback = vi.spyOn(api, "getChat").mockResolvedValue(history);
    const controller = new AbortController();

    prefetchChatHistory("prefetched-chat", "A", controller.signal);
    await sessionApi.getSession("prefetched-chat");

    expect(prefetched).toHaveBeenCalledOnce();
    expect(fallback).not.toHaveBeenCalled();
  });

  it("shares concurrent first sends and publishes the created Chat once", async () => {
    const pending = deferred<ChatSpec>();
    const create = vi.spyOn(api, "createChat").mockReturnValue(pending.promise);
    const selected = vi.fn();
    sessionApi.onSessionCreated = selected;
    const bound = sessionApi.bindToOwner();
    const results = Promise.all([
      sessionApi.createSession({ name: "first" }),
      bound.createSession({ name: "second" }),
      sessionApi.createSession({ name: "third" }),
    ]);
    pending.resolve(createdChat("chat-one"));
    const sessions = await results;

    expect(create).toHaveBeenCalledTimes(1);
    expect(create).toHaveBeenCalledWith(
      expect.objectContaining({ name: "first" }),
    );
    expect(sessions[1]).toBe(sessions[0]);
    expect(sessions[2]).toBe(sessions[0]);
    sessionApi.activateCreatedSession("chat-one");
    expect(selected).toHaveBeenCalledExactlyOnceWith("chat-one");
    expect(sessions[0]).toMatchObject({
      session: { id: "chat-one", sessionId: "runtime-chat-one" },
      sessions: [{ id: "chat-one" }],
    });
  });

  it("creates another Chat after the previous creation has completed", async () => {
    const create = vi
      .spyOn(api, "createChat")
      .mockResolvedValueOnce(createdChat("chat-one"))
      .mockResolvedValueOnce(createdChat("chat-two"));
    await sessionApi.createSession({ name: "first" });
    const next = await sessionApi.createSession({ name: "second" });

    expect(create).toHaveBeenCalledTimes(2);
    expect(next.session.id).toBe("chat-two");
    expect(next.sessions.map((session) => session.id)).toEqual([
      "chat-two",
      "chat-one",
    ]);
  });

  it("publishes a newly created Chat in Today before any list refresh", async () => {
    const now = new Date().toISOString();
    const chat = {
      ...createdChat("chat-today"),
      created_at: now,
      updated_at: now,
    };
    vi.spyOn(api, "createChat").mockResolvedValue(chat);
    const result = await sessionApi.createSession({ name: "first message" });

    const groups = groupChatsByDate(result.sessions as ExtendedSession[]);
    expect(groups.map((group) => group.key)).toEqual(["today"]);
    expect(result.session).toMatchObject({
      createdAt: chat.created_at,
      updatedAt: chat.updated_at,
    });
  });

  it("rejects all waiters on failure and allows a fresh concurrent retry", async () => {
    const pending = deferred<ChatSpec>();
    const failure = new Error("create failed");
    const create = vi.spyOn(api, "createChat").mockReturnValue(pending.promise);
    const selected = vi.fn();
    sessionApi.onSessionCreated = selected;
    const failed = Promise.allSettled([
      sessionApi.createSession({ name: "first" }),
      sessionApi.createSession({ name: "second" }),
    ]);
    pending.reject(failure);
    expect(await failed).toEqual([
      { status: "rejected", reason: failure },
      { status: "rejected", reason: failure },
    ]);
    expect(selected).not.toHaveBeenCalled();
    const attemptsBeforeRetry = create.mock.calls.length;
    const retry = deferred<ChatSpec>();
    create.mockReturnValue(retry.promise);
    const retried = Promise.all([
      sessionApi.createSession({ name: "retry" }),
      sessionApi.createSession({ name: "retry again" }),
    ]);
    retry.resolve(createdChat("retry-chat"));
    const results = await retried;

    expect(attemptsBeforeRetry).toBe(1);
    expect(create).toHaveBeenCalledTimes(2);
    expect(results[0]).toBe(results[1]);
    sessionApi.activateCreatedSession("retry-chat");
    expect(selected).toHaveBeenCalledExactlyOnceWith("retry-chat");
  });

  it.each(["resolve", "reject"] as const)(
    "does not let an old A %s clear the new A epoch's pending creation",
    async (settle) => {
      const old = deferred<ChatSpec>();
      const current = deferred<ChatSpec>();
      const create = vi.spyOn(api, "createChat").mockReturnValue(old.promise);
      const selected = vi.fn();
      sessionApi.onSessionCreated = selected;
      const oldResult = Promise.allSettled([
        sessionApi.createSession({ name: "old A" }),
      ]);
      const oldBound = sessionApi.bindToOwner();
      sessionApi.setActiveAgent("B");
      sessionApi.setActiveAgent("A");
      create.mockReturnValue(current.promise);
      const newResult = sessionApi.createSession({ name: "new A" });
      const identityBefore =
        sessionApi.getSessionIdentity("fresh-chat").sessionId;
      if (settle === "resolve") old.resolve(createdChat("stale-chat"));
      else old.reject(new Error("old failure"));
      const [stale] = await oldResult;
      expect(stale.status).toBe("rejected");
      if (settle === "resolve" && stale.status === "rejected") {
        expect(stale.reason).toMatchObject({ name: "AbortError" });
      }
      expect(selected).not.toHaveBeenCalled();
      expect(sessionApi.getSessionIdentity("fresh-chat").sessionId).toBe(
        identityBefore,
      );
      await expect(oldBound.createSession({})).rejects.toMatchObject({
        name: "AbortError",
      });
      const joined = sessionApi.createSession({ name: "join new A" });
      current.resolve(createdChat("fresh-chat"));
      const [result, joinedResult] = await Promise.all([newResult, joined]);

      expect(create).toHaveBeenCalledTimes(2);
      expect(joinedResult).toBe(result);
      expect(result.sessions.map((session) => session.id)).toEqual([
        "fresh-chat",
      ]);
      expect(sessionApi.getSessionIdentity("fresh-chat").sessionId).toBe(
        "runtime-fresh-chat",
      );
      sessionApi.activateCreatedSession("fresh-chat");
      expect(selected).toHaveBeenCalledExactlyOnceWith("fresh-chat");
    },
  );

  it("rejects late old-A success after new-A success without changing identity or list", async () => {
    const old = deferred<ChatSpec>();
    const create = vi.spyOn(api, "createChat").mockReturnValue(old.promise);
    const selected = vi.fn();
    sessionApi.onSessionCreated = selected;
    const stale = Promise.allSettled([sessionApi.createSession({})]);
    sessionApi.setActiveAgent("B");
    sessionApi.setActiveAgent("A");
    create.mockResolvedValue(createdChat("fresh-chat"));
    const fresh = await sessionApi.createSession({});
    old.resolve(createdChat("stale-chat"));
    expect(await stale).toEqual([
      {
        status: "rejected",
        reason: expect.objectContaining({ name: "AbortError" }),
      },
    ]);
    expect(sessionApi.getSessionIdentity("fresh-chat").sessionId).toBe(
      "runtime-fresh-chat",
    );
    sessionApi.activateCreatedSession("fresh-chat");
    expect(selected).toHaveBeenCalledExactlyOnceWith("fresh-chat");
    create.mockResolvedValue(createdChat("next-chat"));
    const next = await sessionApi.createSession({});
    expect(fresh.session.id).toBe("fresh-chat");
    expect(next.sessions.map((session) => session.id)).toEqual([
      "next-chat",
      "fresh-chat",
    ]);
  });
});

describe("bound session history owner epochs", () => {
  beforeEach(() => {
    sessionApi.resetForTests();
    sessionApi.setActiveAgent("A");
  });

  afterEach(() => {
    vi.restoreAllMocks();
    sessionApi.resetForTests();
  });

  it("suppresses A1's late idle observer after A -> B -> A2 while preserving direct getSession results", async () => {
    const chatId = "11111111-1111-4111-8111-111111111111";
    const pending = deferred<ChatHistory>();
    const history = vi.spyOn(api, "getChat").mockReturnValue(pending.promise);
    const clearLoading = vi.fn();
    const oldObserver = vi.fn((_id, session) => {
      if (session && !session.generating) clearLoading();
    });
    const oldBound = sessionApi.bindToOwner();
    const oldAdapter = createSdkSessionAdapter(oldBound, oldObserver);
    // Use the real SessionApi and adapter; defer only the backend history.
    const boundResult = oldAdapter.api.getSession(chatId);
    const directResult = sessionApi.getSession(chatId);
    expect(history).toHaveBeenCalledTimes(1);

    sessionApi.setActiveAgent("B");
    sessionApi.setActiveAgent("A");
    history.mockResolvedValue({ messages: [], status: "running" });
    const currentObserver = vi.fn();
    const currentAdapter = createSdkSessionAdapter(
      sessionApi.bindToOwner(),
      currentObserver,
    );
    const current = await currentAdapter.api.getSession(chatId);
    expect(current).toMatchObject({ id: chatId, generating: true });
    expect(currentAdapter.isReady(chatId)).toBe(true);
    expect(currentObserver).toHaveBeenCalledExactlyOnceWith(chatId, current);

    pending.resolve({ messages: [], status: "idle" });
    const [staleBound, staleDirect] = await Promise.all([
      boundResult,
      directResult,
    ]);
    expect(oldObserver).not.toHaveBeenCalled();
    expect(clearLoading).not.toHaveBeenCalled();
    expect(staleBound).toBeUndefined();
    expect(oldAdapter.isReady(chatId)).toBe(false);
    expect(staleDirect).toMatchObject({ id: chatId, generating: false });
    expect(currentAdapter.isReady(chatId)).toBe(true);
    expect(currentObserver).toHaveBeenCalledTimes(1);

    // The original pre-call guard must also reject newly invoked stale APIs.
    await expect(oldBound.getSession(chatId)).resolves.toBeUndefined();
    expect(history).toHaveBeenCalledTimes(2);
  });

  it("still delivers current-owner idle history to the observer", async () => {
    const chatId = "22222222-2222-4222-8222-222222222222";
    vi.spyOn(api, "getChat").mockResolvedValue({
      messages: [],
      status: "idle",
    });
    const observer = vi.fn();
    const adapter = createSdkSessionAdapter(sessionApi.bindToOwner(), observer);
    const session = await adapter.api.getSession(chatId);

    expect(session).toMatchObject({ id: chatId, generating: false });
    expect(observer).toHaveBeenCalledExactlyOnceWith(chatId, session);
    expect(adapter.isReady(chatId)).toBe(true);
  });
});

describe("durable transcript pagination", () => {
  beforeEach(() => {
    sessionApi.resetForTests();
    sessionApi.setActiveAgent("A");
  });

  afterEach(() => {
    vi.restoreAllMocks();
    sessionApi.resetForTests();
  });

  it("loads the complete user index and jumps through an opaque anchor", async () => {
    const chatId = "77777777-7777-4777-8777-777777777777";
    const getUserMessages = vi
      .spyOn(api, "getChatUserMessages")
      .mockResolvedValueOnce({
        items: [
          {
            message_id: "user-3",
            preview: "three",
            created_at: "2026-10-23T03:00:00Z",
            anchor: "anchor-3",
          },
        ],
        has_more: true,
        next_before: "index-cursor",
      })
      .mockResolvedValueOnce({
        items: [
          {
            message_id: "user-1",
            preview: "one",
            created_at: "2026-10-23T01:00:00Z",
            anchor: "anchor-1",
          },
          {
            message_id: "user-2",
            preview: "two",
            created_at: "2026-10-23T02:00:00Z",
            anchor: "anchor-2",
          },
        ],
        has_more: false,
        next_before: null,
      });
    const getMessages = vi.spyOn(api, "getChatMessages").mockResolvedValue({
      messages: [msg({ id: "user-1", content: "one" })],
      has_more: false,
      next_before: null,
    });

    const firstIndexPage = await sessionApi.loadUserMessageIndexPage(chatId);
    expect(getUserMessages).toHaveBeenCalledTimes(1);
    expect(firstIndexPage.items.map((item) => item.messageId)).toEqual([
      "user-3",
    ]);
    const olderIndexPage = await sessionApi.loadUserMessageIndexPage(
      chatId,
      firstIndexPage.before,
    );
    const index = [...olderIndexPage.items, ...firstIndexPage.items];
    const target = await sessionApi.loadHistoryAtAnchor(
      chatId,
      "anchor-1",
      "user-1",
    );

    expect(index.map((item) => item.messageId)).toEqual([
      "user-1",
      "user-2",
      "user-3",
    ]);
    expect(getUserMessages).toHaveBeenNthCalledWith(2, chatId, {
      before: "index-cursor",
      limit: 50,
      signal: undefined,
      include_app_owned: false,
    });
    expect(getMessages).toHaveBeenCalledWith(chatId, {
      before: "anchor-1",
      limit: 5,
      signal: undefined,
      include_app_owned: false,
    });
    expect(target.messages[0]).toMatchObject({
      id: "user-1",
      role: "user",
    });
  });

  it("publishes a navigation fragment and resumes from its cursor", async () => {
    const chatId = "44444444-4444-4444-8444-444444444444";
    const getMessages = vi
      .spyOn(api, "getChatMessages")
      .mockResolvedValueOnce({
        messages: [msg({ id: "assistant-fragment", content: "tail" })],
        has_more: true,
        next_before: "fragment-cursor",
      })
      .mockResolvedValueOnce({
        messages: [msg({ id: "target-user", content: "target" })],
        has_more: true,
        next_before: "older-cursor",
      });

    const target = await sessionApi.loadHistoryAtAnchor(
      chatId,
      "target-anchor",
      "target-user",
    );

    expect(getMessages).toHaveBeenCalledTimes(1);
    expect(target.messages.map((message) => message.id)).toEqual([
      "assistant-fragment",
    ]);
    const resumed = await sessionApi.loadOlderHistory(chatId);
    expect(getMessages).toHaveBeenCalledTimes(2);
    expect(getMessages).toHaveBeenNthCalledWith(2, chatId, {
      before: "fragment-cursor",
      limit: 5,
      signal: undefined,
      include_app_owned: false,
    });
    expect(resumed.messages.map((message) => message.id)).toEqual([
      "target-user",
      "assistant-fragment",
    ]);
    expect(target.noMore).toBe(false);
  });

  it("keeps the older boundary after a forward fill and resets it on navigation", async () => {
    const chatId = "44444444-4444-4444-8444-444444444444";
    const getMessages = vi.spyOn(api, "getChatMessages");
    getMessages.mockResolvedValueOnce({
      messages: [msg({ id: "user-8", content: "eight" })],
      has_more: true,
      next_before: "before-4",
    });
    await sessionApi.loadHistoryAtAnchor(chatId, "anchor-8", "user-8");
    getMessages.mockResolvedValueOnce({
      messages: [msg({ id: "user-13", content: "thirteen" })],
      has_more: true,
      next_before: "before-9",
    });
    await sessionApi.loadHistoryAtAnchor(
      chatId,
      "anchor-13",
      "user-13",
      undefined,
      "append-newer",
    );
    getMessages.mockResolvedValueOnce({
      messages: [msg({ id: "user-1", content: "one" })],
      has_more: false,
      next_before: null,
    });
    const older = await sessionApi.loadOlderHistory(chatId);
    expect(getMessages).toHaveBeenLastCalledWith(
      chatId,
      expect.objectContaining({ before: "before-4" }),
    );
    expect(older.noMore).toBe(true);
    expect(older.messages.some((item) => item.id === "user-1")).toBe(true);

    getMessages.mockResolvedValueOnce({
      messages: [msg({ id: "user-20", content: "twenty" })],
      has_more: true,
      next_before: "before-16",
    });
    await sessionApi.loadHistoryAtAnchor(chatId, "anchor-20", "user-20");
    getMessages.mockResolvedValueOnce({
      messages: [msg({ id: "user-15", content: "fifteen" })],
      has_more: true,
      next_before: "before-11",
    });
    await sessionApi.loadOlderHistory(chatId);
    expect(getMessages).toHaveBeenLastCalledWith(
      chatId,
      expect.objectContaining({ before: "before-16" }),
    );
  });

  it("resumes a forward turn on the next interaction without skipping fragments", async () => {
    const getMessages = vi
      .spyOn(api, "getChatMessages")
      .mockResolvedValueOnce({
        messages: [msg({ id: "reply-993", role: "assistant", content: "993" })],
        has_more: true,
        next_before: "inside-993",
      })
      .mockResolvedValueOnce({
        messages: [msg({ id: "user-993", content: "993" })],
        has_more: true,
        next_before: "before-993",
      });
    const page = await sessionApi.loadHistoryAtAnchor(
      "44444444-4444-4444-8444-444444444444",
      "anchor-997",
      "user-992",
      undefined,
      "append-newer",
    );
    expect(getMessages).toHaveBeenCalledTimes(1);
    expect(page.messages).toHaveLength(1);
    const prefix = await sessionApi.loadHistoryAtAnchor(
      "44444444-4444-4444-8444-444444444444",
      "anchor-997",
      "user-992",
      undefined,
      "append-newer",
    );
    expect(getMessages).toHaveBeenCalledTimes(2);
    const combined = T.mergeHistoryMessages(prefix.messages, page.messages);
    expect(combined).toHaveLength(2);
    expect(combined[0].id).toBe("user-993");
    expect(getMessages.mock.calls[0][1]).toMatchObject({
      after_message_id: "user-992",
      limit: 1,
    });
    expect(getMessages.mock.calls[0][1]).not.toHaveProperty("before");
    expect(getMessages.mock.calls[1][1]).toMatchObject({
      before: "inside-993",
      limit: 1,
    });
  });

  it("restores the latest messages and cursor after repeated anchor navigation", async () => {
    const chatId = "33333333-3333-4333-8333-333333333333";
    vi.spyOn(api, "getChat").mockResolvedValue({
      messages: [msg({ id: "latest-user", content: "latest" })],
      status: "idle",
      history: { has_more: true, next_before: "latest-cursor" },
    });
    const getMessages = vi.spyOn(api, "getChatMessages").mockResolvedValue({
      messages: [msg({ id: "old-user", content: "old" })],
      has_more: false,
      next_before: null,
    });
    await sessionApi.getSession(chatId);
    await sessionApi.loadHistoryAtAnchor(chatId, "anchor-1", "old-user");
    await sessionApi.loadHistoryAtAnchor(chatId, "anchor-2", "old-user");
    expect(
      sessionApi.showLatestHistory(chatId)?.map((item) => item.id),
    ).toEqual(["latest-user"]);
    await sessionApi.loadOlderHistory(chatId);
    expect(getMessages).toHaveBeenLastCalledWith(
      chatId,
      expect.objectContaining({ before: "latest-cursor" }),
    );
    getMessages.mockResolvedValueOnce({
      messages: [msg({ id: "newest-user", content: "newest" })],
      has_more: true,
      next_before: "newest-cursor",
    });
    await sessionApi.loadHistoryAtAnchor(
      chatId,
      "newest-anchor",
      "newest-user",
      undefined,
      "replace",
      true,
    );
    await sessionApi.loadHistoryAtAnchor(chatId, "anchor-1", "old-user");
    expect(
      sessionApi.showLatestHistory(chatId)?.map((item) => item.id),
    ).toEqual(["newest-user"]);
  });

  it("loads one older page and stops after the cursor is exhausted", async () => {
    const chatId = "33333333-3333-4333-8333-333333333333";
    vi.spyOn(api, "getChat").mockResolvedValue({
      messages: [msg({ id: "new-user", content: "new" })],
      status: "idle",
      history: {
        has_more: true,
        next_before: "2:0",
      },
    });
    const getMessages = vi.spyOn(api, "getChatMessages").mockResolvedValue({
      messages: [msg({ id: "old-user", content: "old" })],
      has_more: false,
      next_before: null,
    });

    await sessionApi.getSession(chatId);
    const first = await sessionApi.loadOlderHistory(chatId);
    const exhausted = await sessionApi.loadOlderHistory(chatId);

    expect(getMessages).toHaveBeenCalledExactlyOnceWith(chatId, {
      before: "2:0",
      limit: 5,
      signal: undefined,
      include_app_owned: false,
    });
    expect(first.messages).toHaveLength(2);
    expect(first.messages[0]).toMatchObject({
      id: "old-user",
      role: "user",
      history: true,
    });
    expect(first.noMore).toBe(true);
    expect(exhausted).toEqual({ messages: [], noMore: true });
  });

  it("publishes a split assistant immediately and fetches its prefix separately", async () => {
    const chatId = "33333333-3333-4333-8333-333333333333";
    vi.spyOn(api, "getChat").mockResolvedValue({
      messages: [msg({ id: "latest", content: "latest" })],
      status: "idle",
      history: { has_more: true, next_before: "start" },
    });
    const tail = deferred<Awaited<ReturnType<typeof api.getChatMessages>>>();
    const getMessages = vi
      .spyOn(api, "getChatMessages")
      .mockResolvedValueOnce({
        messages: [
          msg({ id: "assistant-tail", role: "assistant", content: "tail" }),
        ],
        has_more: true,
        next_before: "middle",
      })
      .mockReturnValueOnce(tail.promise);
    await sessionApi.getSession(chatId);
    const published = vi.fn();
    await sessionApi.loadOlderHistory(chatId).then(published);
    expect(getMessages).toHaveBeenCalledTimes(1);
    expect(published).toHaveBeenCalledOnce();
    const load = sessionApi.loadOlderHistory(chatId);
    await vi.waitFor(() => expect(getMessages).toHaveBeenCalledTimes(2));
    expect(getMessages).toHaveBeenLastCalledWith(
      chatId,
      expect.objectContaining({
        before: "middle",
        limit: 5,
      }),
    );
    tail.resolve({
      messages: [msg({ id: "older-user", content: "question" })],
      has_more: true,
      next_before: "previous-turn",
    });
    const resumed = await load;
    expect(resumed.messages.map((item) => item.id)).toEqual([
      "older-user",
      expect.any(String),
    ]);
    const data = resumed.messages[1].cards?.[0].data as {
      output: { id: string }[];
    };
    expect(data.output[0].id).toBe("assistant-tail");
  });

  it("does not commit a staged partial page when it is canceled", async () => {
    const chatId = "33333333-3333-4333-8333-333333333333";
    vi.spyOn(api, "getChat").mockResolvedValue({
      messages: [msg({ id: "latest", content: "latest" })],
      status: "idle",
      history: { has_more: true, next_before: "start" },
    });
    const controller = new AbortController();
    const getMessages = vi
      .spyOn(api, "getChatMessages")
      .mockImplementationOnce(async () => {
        controller.abort();
        return {
          messages: [msg({ id: "tail", role: "assistant", content: "tail" })],
          has_more: true,
          next_before: "middle",
        };
      });
    await sessionApi.getSession(chatId);
    await expect(
      sessionApi.loadOlderHistory(chatId, controller.signal),
    ).rejects.toMatchObject({ name: "AbortError" });
    getMessages.mockResolvedValueOnce({ messages: [], has_more: false });
    await sessionApi.loadOlderHistory(chatId);
    expect(getMessages).toHaveBeenLastCalledWith(
      chatId,
      expect.objectContaining({ before: "start" }),
    );
  });

  it("keeps only adjacent pages in the SDK history window", async () => {
    const chatId = "55555555-5555-4555-8555-555555555555";
    vi.spyOn(api, "getChat").mockResolvedValue({
      messages: [
        msg({ id: "new-user-1", content: "new 1" }),
        msg({ id: "new-user-2", content: "new 2" }),
      ],
      status: "idle",
      history: {
        has_more: true,
        next_before: "3:0",
      },
    });
    const getMessages = vi
      .spyOn(api, "getChatMessages")
      .mockResolvedValueOnce({
        messages: [
          msg({ id: "middle-user-1", content: "middle 1" }),
          msg({ id: "middle-user-2", content: "middle 2" }),
        ],
        has_more: true,
        next_before: "2:0",
      })
      .mockResolvedValueOnce({
        messages: [
          msg({ id: "old-user-1", content: "old 1" }),
          msg({ id: "old-user-2", content: "old 2" }),
        ],
        has_more: false,
        next_before: null,
      });

    await sessionApi.getSession(chatId);
    const middle = await sessionApi.loadOlderHistory(chatId);
    const oldest = await sessionApi.loadOlderHistory(chatId);
    const newer = sessionApi.loadNewerHistory(chatId);
    const latest = sessionApi.loadNewerHistory(chatId);

    expect(middle.messages.map((message) => message.id)).toEqual([
      "middle-user-1",
      "middle-user-2",
      "new-user-1",
    ]);
    expect(oldest.messages.map((message) => message.id)).toEqual([
      "old-user-1",
      "old-user-2",
      "middle-user-1",
    ]);
    expect(newer?.messages.map((message) => message.id)).toEqual([
      "middle-user-1",
      "middle-user-2",
      "new-user-1",
    ]);
    expect(latest?.messages.map((message) => message.id)).toEqual([
      "new-user-1",
      "new-user-2",
    ]);
    expect(newer?.canLoadOlder).toBe(true);
    expect(latest?.canLoadOlder).toBe(true);
    expect(sessionApi.loadNewerHistory(chatId)).toBeNull();
    expect(getMessages).toHaveBeenCalledTimes(2);
  });

  it("accumulates short pages only for automatic viewport fill", async () => {
    const chatId = "66666666-6666-4666-8666-666666666666";
    vi.spyOn(api, "getChat").mockResolvedValue({
      messages: [msg({ id: "new-user", content: "new" })],
      status: "idle",
      history: { has_more: true, next_before: "3:0" },
    });
    vi.spyOn(api, "getChatMessages")
      .mockResolvedValueOnce({
        messages: [msg({ id: "middle-user", content: "middle" })],
        has_more: true,
        next_before: "2:0",
      })
      .mockResolvedValueOnce({
        messages: [msg({ id: "old-user", content: "old" })],
        has_more: false,
        next_before: null,
      });

    await sessionApi.getSession(chatId);
    const middle = await sessionApi.loadOlderHistory(chatId, undefined, true);
    const oldest = await sessionApi.loadOlderHistory(chatId, undefined, true);

    expect(middle.messages.map((message) => message.id)).toEqual([
      "middle-user",
      "new-user",
    ]);
    expect(oldest.messages.map((message) => message.id)).toEqual([
      "old-user",
      "middle-user",
      "new-user",
    ]);
    expect(oldest.noMore).toBe(true);
    expect(sessionApi.loadNewerHistory(chatId)).toBeNull();
  });

  it("releases a failed page request so an explicit retry can succeed", async () => {
    const chatId = "44444444-4444-4444-8444-444444444444";
    vi.spyOn(api, "getChat").mockResolvedValue({
      messages: [],
      status: "idle",
      history: {
        has_more: true,
        next_before: "2:0",
      },
    });
    const getMessages = vi
      .spyOn(api, "getChatMessages")
      .mockRejectedValueOnce(new Error("temporarily unavailable"))
      .mockResolvedValueOnce({
        messages: [msg({ id: "old-user", content: "old" })],
        has_more: false,
        next_before: null,
      });

    await sessionApi.getSession(chatId);
    await expect(sessionApi.loadOlderHistory(chatId)).rejects.toThrow(
      "temporarily unavailable",
    );

    const retried = await sessionApi.loadOlderHistory(chatId);

    expect(getMessages).toHaveBeenCalledTimes(2);
    expect(retried.messages).toHaveLength(1);
    expect(retried.noMore).toBe(true);
  });

  it("merges assistant fragments when one turn spans history pages", () => {
    const fragment = (id: string, ordinal: number) =>
      msg({
        id,
        role: "assistant",
        content: `part ${ordinal}`,
        metadata: {
          qwenpaw_transcript_position: {
            turn_id: "turn-1",
            turn_seq: 1,
            ordinal,
          },
        },
      });
    const older = T.convertMessages([fragment("m1", 1), fragment("m2", 2)]);
    const newer = T.convertMessages([fragment("m3", 3), fragment("m4", 4)]);

    const merged = T.mergeHistoryMessages(older, newer);

    expect(merged).toHaveLength(1);
    expect(merged[0].id).toBe("history-turn:turn-1");
    const data = merged[0].cards?.[0]?.data as {
      output?: Array<{ id?: string }>;
    };
    expect(data.output?.map((item) => item.id)).toEqual([
      "m1",
      "m2",
      "m3",
      "m4",
    ]);
  });

  it.each(["user", "assistant"])(
    "merges %s content fragments back into one message",
    (role) => {
      const fragment = (start: number, end: number, labels: string[]) =>
        msg({
          id: "fragmented-message",
          role,
          content: labels.map((text) => ({ type: "text", text })),
          metadata: {
            qwenpaw_transcript_position: {
              turn_id: "turn-fragment",
              turn_seq: 1,
              ordinal: role === "user" ? 0 : 1,
            },
            qwenpaw_history_fragment: {
              content_start: start,
              content_end: end,
              content_total: 3,
            },
          },
        });
      const older = T.convertMessages([fragment(0, 1, ["first"])]);
      const newer = T.convertMessages([fragment(1, 3, ["second", "third"])]);

      const merged = T.mergeHistoryMessages(older, newer);
      expect(merged).toHaveLength(1);
      const data = merged[0].cards?.[0]?.data as {
        input?: Array<{ content: Array<{ text: string }> }>;
        output?: Array<{ content: Array<{ text: string }> }>;
      };
      const message = role === "user" ? data.input?.[0] : data.output?.[0];
      expect(message).toBeDefined();
      expect(message?.content.map((item) => item.text)).toEqual([
        "first",
        "second",
        "third",
      ]);
    },
  );

  it("merges text slices inside one oversized content block", () => {
    const fragment = (start: number, end: number, text: string) =>
      msg({
        id: "fragmented-text-message",
        role: "assistant",
        content: [{ type: "text", text }],
        metadata: {
          qwenpaw_transcript_position: {
            turn_id: "turn-fragment",
            turn_seq: 1,
            ordinal: 1,
          },
          qwenpaw_history_fragment: {
            content_start: 0,
            content_end: 1,
            content_total: 1,
            text_content_index: 0,
            text_start: start,
            text_end: end,
            text_total: 11,
          },
        },
      });
    const older = T.convertMessages([fragment(0, 6, "hello ")]);
    const newer = T.convertMessages([fragment(6, 11, "world")]);

    const merged = T.mergeHistoryMessages(older, newer);
    expect(merged).toHaveLength(1);
    const data = merged[0].cards?.[0]?.data as {
      output?: Array<{
        content: Array<{ text: string }>;
        metadata?: Record<string, unknown>;
      }>;
    };
    expect(data.output?.[0]?.content[0]?.text).toBe("hello world");
    expect(data.output?.[0]?.metadata?.qwenpaw_history_fragment).toEqual({
      content_start: 0,
      content_end: 1,
      content_total: 1,
    });
  });

  it("restores a serialized oversized tool result block", () => {
    const block = JSON.stringify({
      type: "data",
      data: {
        call_id: "call-1",
        name: "large_tool",
        output: "hello world",
      },
    });
    const firstSplit = Math.floor(block.length / 3);
    const secondSplit = Math.floor((block.length * 2) / 3);
    const fragment = (start: number, end: number) =>
      msg({
        id: "fragmented-tool-result",
        role: "assistant",
        content: [],
        metadata: {
          qwenpaw_transcript_position: {
            turn_id: "turn-fragment",
            turn_seq: 1,
            ordinal: 1,
          },
          qwenpaw_history_fragment: {
            content_start: 0,
            content_end: 1,
            content_total: 1,
            serialized_start: start,
            serialized_end: end,
            serialized_total: block.length,
            serialized_fragment: block.slice(start, end),
          },
        },
      });
    const oldest = T.convertMessages([fragment(0, firstSplit)]);
    const middle = T.convertMessages([fragment(firstSplit, secondSplit)]);
    const newest = T.convertMessages([fragment(secondSplit, block.length)]);

    const partial = T.mergeHistoryMessages(middle, newest);
    const partialData = partial[0].cards?.[0]?.data as {
      output?: Array<{
        metadata?: {
          qwenpaw_history_fragment?: {
            serialized_fragments?: string[];
          };
        };
      }>;
    };
    expect(
      partialData.output?.[0]?.metadata?.qwenpaw_history_fragment
        ?.serialized_fragments,
    ).toEqual([block.slice(firstSplit, secondSplit), block.slice(secondSplit)]);

    const merged = T.mergeHistoryMessages(oldest, partial);
    expect(merged).toHaveLength(1);
    const data = merged[0].cards?.[0]?.data as {
      output?: Array<{
        content: Array<Record<string, unknown>>;
        metadata?: Record<string, unknown>;
      }>;
    };
    expect(data.output?.[0]?.content).toEqual([JSON.parse(block)]);
    expect(data.output?.[0]?.metadata?.qwenpaw_history_fragment).toEqual({
      content_start: 0,
      content_end: 1,
      content_total: 1,
    });
  });

  it.each(["failed", "canceled"] as const)(
    "keeps empty %s response timestamps stable across reloads",
    (status) => {
      const input = [
        msg({
          metadata: {
            timestamp: "2026-10-26T04:40:18+00:00",
            qwenpaw_turn_state: {
              status,
              finished_at: "2026-10-26T04:40:31+00:00",
            },
          },
        }),
      ];
      const first = T.convertMessages(input, true)[1].cards?.[0]?.data;
      const now = vi.spyOn(Date, "now").mockReturnValue(2000000000000);
      try {
        const reloaded = T.convertMessages(input, true)[1].cards?.[0]?.data;
        expect(first).toMatchObject({
          created_at: Date.parse("2026-10-26T04:40:18Z") / 1000,
          completed_at: Date.parse("2026-10-26T04:40:31Z") / 1000,
        });
        expect(reloaded).toMatchObject({
          created_at: first.created_at,
          completed_at: first.completed_at,
        });
      } finally {
        now.mockRestore();
      }
    },
  );

  it.each(["failed", "canceled", "completed"] as const)(
    "preserves %s when one turn spans history pages",
    (status) => {
      const transcriptPosition = (ordinal: number) => ({
        turn_id: "turn-terminal",
        turn_seq: 1,
        ordinal,
      });
      const older = T.convertMessages([
        msg({
          id: "terminal-user",
          metadata: {
            qwenpaw_transcript_position: transcriptPosition(0),
            qwenpaw_turn_state: {
              status,
              error: status === "failed" ? { message: "boom" } : null,
            },
          },
        }),
      ]);
      const newer = T.convertMessages([
        msg({
          id: "terminal-assistant",
          role: "assistant",
          content: "partial response",
          metadata: {
            qwenpaw_transcript_position: transcriptPosition(1),
          },
        }),
      ]);

      const merged = T.mergeHistoryMessages(older, newer);
      const response = merged.find((message) => message.role === "assistant");
      const data = response?.cards?.find(
        (card) => card.code === "AgentScopeRuntimeResponseCard",
      )?.data as { status?: string; error?: unknown } | undefined;

      expect(data?.status).toBe(status);
      if (status === "failed") {
        expect(data?.error).toEqual({ message: "boom" });
      }
      expect(response?.msgStatus).toBe(
        status === "canceled" ? "interrupted" : "finished",
      );
    },
  );
});

type SessionLike = {
  id: string;
  name?: string;
  sessionId?: string;
  realId?: string;
};

const msg = (over: Record<string, unknown> = {}) => ({
  id: "m1",
  role: "user",
  type: "message",
  content: "hello",
  metadata: null,
  ...over,
});

describe("parseTimestamp / parseFinishedAt", () => {
  it("parses a metadata timestamp to unix seconds", () => {
    const m = msg({ metadata: { timestamp: "2026-05-27 10:44:53.362" } });
    const sec = T.parseTimestamp(m as never);
    expect(sec).toBe(
      Math.floor(new Date("2026-05-27T10:44:53.362").getTime() / 1000),
    );
  });

  it("returns 0 for missing metadata", () => {
    expect(T.parseTimestamp(msg() as never)).toBe(0);
    expect(T.parseFinishedAt(msg() as never)).toBe(0);
  });

  it("returns 0 for unparseable strings", () => {
    const m = msg({ metadata: { timestamp: "not a date", finished_at: 42 } });
    expect(T.parseTimestamp(m as never)).toBe(0);
    expect(T.parseFinishedAt(m as never)).toBe(0);
  });

  it("reads finished_at independently of timestamp", () => {
    const m = msg({
      metadata: {
        timestamp: "2026-01-01 00:00:00",
        finished_at: "2026-01-02 00:00:00",
      },
    });
    const ts = T.parseTimestamp(m as never);
    const fa = T.parseFinishedAt(m as never);
    expect(fa).toBeGreaterThan(ts);
  });
});

describe("extractTextFromContent", () => {
  it("returns strings as-is", () => {
    expect(T.extractTextFromContent("plain")).toBe("plain");
  });

  it("joins text items and ignores other types", () => {
    expect(
      T.extractTextFromContent([
        { type: "text", text: "a" },
        { type: "image" },
        { type: "text", text: "b" },
        { type: "text" },
      ]),
    ).toBe("a\nb");
  });

  it("stringifies non-array non-string content", () => {
    expect(T.extractTextFromContent(null)).toBe("");
    expect(T.extractTextFromContent(5)).toBe("5");
  });
});

describe("contentToRequestParts", () => {
  it("wraps plain strings into a text part", () => {
    expect(T.contentToRequestParts("hi")).toEqual([
      { type: "text", text: "hi", status: "created" },
    ]);
  });

  it("returns a single empty text part for empty arrays", () => {
    expect(T.contentToRequestParts([])).toEqual([
      { type: "text", text: "", status: "created" },
    ]);
  });

  it("tags every part with created status", () => {
    const parts = T.contentToRequestParts([{ type: "text", text: "x" }]);
    expect(parts[0].status).toBe("created");
  });
});

describe("toOutputMessage", () => {
  it("maps system plugin_call_output to the tool role", () => {
    const out = T.toOutputMessage(
      msg({ role: "system", type: "plugin_call_output" }) as never,
    );
    expect(out.role).toBe("tool");
  });

  it("keeps other roles untouched and nulls missing metadata", () => {
    const out = T.toOutputMessage(
      msg({ role: "assistant", metadata: undefined }) as never,
    );
    expect(out.role).toBe("assistant");
    expect(out.metadata).toBeNull();
  });
});

describe("buildUserCard", () => {
  it("uses the message id and parses the created timestamp", () => {
    const card = T.buildUserCard(
      msg({
        id: "fixed-id",
        metadata: { timestamp: "2026-01-01 00:00:00" },
      }) as never,
    );
    expect(card.id).toBe("fixed-id");
    expect(card.role).toBe("user");
    expect(card.cards![0].code).toBe("AgentScopeRuntimeRequestCard");
    expect(card.cards![0].data.created_at).toBeGreaterThan(0);
    expect(card.cards![0].data.input[0].content).toEqual([
      { type: "text", text: "hello", status: "created" },
    ]);
  });

  it("generates an id when the message has none", () => {
    const card = T.buildUserCard(msg({ id: "" }) as never);
    expect(card.id).toBeTruthy();
  });
});

describe("isLocalTimestamp", () => {
  it("recognizes local timestamp-random ids", () => {
    expect(T.isLocalTimestamp("1735689600000-abc12")).toBe(true);
  });

  it("rejects backend UUIDs", () => {
    expect(T.isLocalTimestamp("550e8400-e29b-41d4-a716-446655440000")).toBe(
      false,
    );
    expect(T.isLocalTimestamp("")).toBe(false);
  });
});

describe("isGenerating", () => {
  it("is true only for an explicit running status", () => {
    expect(T.isGenerating({ status: "running" } as never)).toBe(true);
  });

  it("treats missing status as idle (no false reconnects)", () => {
    expect(T.isGenerating({} as never)).toBe(false);
    expect(T.isGenerating({ status: "idle" } as never)).toBe(false);
    expect(T.isGenerating({ status: undefined } as never)).toBe(false);
  });
});

describe("resolveRealId", () => {
  const local = (id: string, over: Partial<SessionLike> = {}) =>
    ({
      id,
      name: id,
      sessionId: undefined,
      realId: undefined,
      ...over,
    }) as SessionLike;

  const LOCAL_ID = "1735689600000-abc12"; // local timestamp-random id

  it("returns an already-resolved realId without mutating the list", () => {
    const list = [local(LOCAL_ID, { realId: "uuid-1" })];
    const { list: out, realId } = T.resolveRealId(list as never, LOCAL_ID);
    expect(realId).toBe("uuid-1");
    expect(out).toBe(list);
  });

  it("links a backend chat whose session_id matches the temp id", () => {
    const placeholder = local(LOCAL_ID);
    const backend = { id: "uuid-2", name: "b", sessionId: LOCAL_ID };
    const { list, realId } = T.resolveRealId(
      [placeholder, backend] as never,
      LOCAL_ID,
    );
    expect(realId).toBe("uuid-2");
    // resolved entry moves to the front and adopts the local id
    expect(list[0].id).toBe(LOCAL_ID);
    expect((list[0] as SessionLike).realId).toBe("uuid-2");
  });

  it("never returns a local timestamp id as the real id", () => {
    const placeholder = local(LOCAL_ID);
    const { realId } = T.resolveRealId([placeholder] as never, LOCAL_ID);
    expect(realId).toBeNull();
  });

  it("returns null when nothing matches", () => {
    const { realId } = T.resolveRealId(
      [local("other-uuid")] as never,
      LOCAL_ID,
    );
    expect(realId).toBeNull();
  });

  it("does not use a placeholder sharing the temp id as the backend uuid", () => {
    const placeholder = local(LOCAL_ID);
    const backendSameId = { id: LOCAL_ID, sessionId: LOCAL_ID };
    const { realId } = T.resolveRealId(
      [placeholder, backendSameId] as never,
      LOCAL_ID,
    );
    // branch 2 skips id===tempSessionId; branch 3 finds the placeholder,
    // whose local-timestamp id must never be treated as a backend UUID.
    expect(realId).toBeNull();
  });
});

describe("normalizeOutputMessageContent", () => {
  it("passes strings through", () => {
    expect(T.normalizeOutputMessageContent("x")).toBe("x");
  });

  it("keeps non-array content unchanged", () => {
    expect(T.normalizeOutputMessageContent(42)).toBe(42);
  });
});

describe("contentToRequestParts", () => {
  it("wraps string content into a created text part", () => {
    expect(T.contentToRequestParts("hi")).toEqual([
      { type: "text", text: "hi", status: "created" },
    ]);
  });

  it("stringifies non-string, non-array content", () => {
    expect(T.contentToRequestParts(null)).toEqual([
      { type: "text", text: "", status: "created" },
    ]);
    expect(T.contentToRequestParts(7)).toEqual([
      { type: "text", text: "7", status: "created" },
    ]);
  });

  it("returns a single empty text part for an empty array", () => {
    expect(T.contentToRequestParts([])).toEqual([
      { type: "text", text: "", status: "created" },
    ]);
  });

  it("resolves image content urls and marks parts created", () => {
    const parts = T.contentToRequestParts([
      { type: "image", image_url: "/files/a.png" },
    ]);
    expect(parts).toHaveLength(1);
    expect(parts[0].status).toBe("created");
    expect(String(parts[0].image_url)).toContain("/files/a.png");
  });

  it("resolves audio data urls", () => {
    const parts = T.contentToRequestParts([
      { type: "audio", data: "/files/b.mp3" },
    ]);
    expect(String(parts[0].data)).toContain("/files/b.mp3");
  });

  it("resolves video urls", () => {
    const parts = T.contentToRequestParts([
      { type: "video", video_url: "/files/c.mp4" },
    ]);
    expect(String(parts[0].video_url)).toContain("/files/c.mp4");
  });

  it("resolves file urls from file_url or file_id with a fallback name", () => {
    const byUrl = T.contentToRequestParts([
      { type: "file", file_url: "/files/d.pdf", filename: "d.pdf" },
    ]);
    expect(String(byUrl[0].file_url)).toContain("/files/d.pdf");
    expect(byUrl[0].file_name).toBe("d.pdf");

    const byId = T.contentToRequestParts([
      { type: "file", file_id: "fid-1", file_name: "named.bin" },
    ]);
    expect(String(byId[0].file_url)).toContain("fid-1");
    expect(byId[0].file_name).toBe("named.bin");

    const unnamed = T.contentToRequestParts([
      { type: "file", file_id: "fid-2" },
    ]);
    expect(unnamed[0].file_name).toBe("file");
  });

  it("passes through content items with no url fields", () => {
    const parts = T.contentToRequestParts([{ type: "text", text: "plain" }]);
    expect(parts[0].text).toBe("plain");
    expect(parts[0].status).toBe("created");
  });
});

describe("creation visit isolation", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    sessionApi.resetForTests();
  });
  it("does not join a prior blank visit or activate a late response", async () => {
    sessionApi.resetForTests();
    const old = deferred<ChatSpec>();
    const fresh = deferred<ChatSpec>();
    const create = vi
      .spyOn(api, "createChat")
      .mockReturnValueOnce(old.promise)
      .mockReturnValueOnce(fresh.promise);
    const selected = vi.fn();
    sessionApi.onSessionCreated = selected;
    const stale = sessionApi.createSession({ name: "old draft" });
    const rejected = expect(stale).rejects.toMatchObject({
      name: "AbortError",
    });
    sessionApi.invalidateSessionCreation();
    const current = sessionApi.createSession({ name: "fresh draft" });
    old.resolve(createdChat("old-chat"));
    await rejected;
    const joined = sessionApi.createSession({ name: "fresh retry" });
    fresh.resolve(createdChat("fresh-chat"));
    expect(await joined).toBe(await current);
    expect(create).toHaveBeenCalledTimes(2);
    expect(selected).not.toHaveBeenCalled();
    sessionApi.activateCreatedSession("old-chat");
    expect(selected).not.toHaveBeenCalled();
    sessionApi.activateCreatedSession("fresh-chat");
    sessionApi.activateCreatedSession("fresh-chat");
    expect(selected).toHaveBeenCalledExactlyOnceWith("fresh-chat");
  });
});

describe("visible session usage ownership", () => {
  beforeEach(() => {
    sessionApi.resetForTests();
    sessionApi.setActiveAgent("A");
  });
  afterEach(() => {
    vi.restoreAllMocks();
    sessionApi.resetForTests();
  });
  it("prefers current context state over historical turn usage", async () => {
    const { useTurnUsageStore } = await import("../turnUsageStore");
    vi.spyOn(api, "getChat").mockResolvedValue({
      messages: [
        {
          role: "assistant",
          content: [{ type: "text", text: "old turn" }],
          metadata: {
            qwenpaw_turn_usage: {
              context_usage: {
                estimated_tokens: 500,
                max_input_length: 100000,
                context_usage_ratio: 0.5,
              },
            },
          },
        },
      ],
      status: "idle",
      context_state: {
        generation: 1,
        usage: {
          usage: null,
          context_usage: {
            estimated_tokens: 0,
            max_input_length: 100000,
            context_usage_ratio: 0,
          },
        },
      },
    } as ChatHistory);

    sessionApi.setVisibleSession("cleared");
    await sessionApi.getSession("cleared");

    expect(useTurnUsageStore.getState().snapshot?.context_usage).toEqual({
      estimated_tokens: 0,
      max_input_length: 100000,
      context_usage_ratio: 0,
    });
  });
  it("does not project a late history response over the selected session", async () => {
    const { useTurnUsageStore } = await import("../turnUsageStore");
    const history = (tokens: number): ChatHistory =>
      ({
        messages: [
          {
            role: "assistant",
            content: [{ type: "text", text: "done" }],
            metadata: {
              qwenpaw_turn_usage: {
                usage: { total_tokens: tokens },
                context_usage: {
                  estimated_tokens: tokens,
                  max_input_length: 100000,
                  context_usage_ratio: tokens / 1000,
                },
              },
            },
          },
        ],
        status: "idle",
      }) as ChatHistory;
    const slow = deferred<ChatHistory>();
    vi.spyOn(api, "getChat").mockImplementation((id) =>
      id === "one" ? slow.promise : Promise.resolve(history(200)),
    );
    sessionApi.setVisibleSession("one");
    const first = sessionApi.getSession("one");
    sessionApi.setVisibleSession("two");
    await sessionApi.getSession("two");
    expect(
      useTurnUsageStore.getState().snapshot?.context_usage?.estimated_tokens,
    ).toBe(200);
    slow.resolve(history(100));
    await first;
    expect(
      useTurnUsageStore.getState().snapshot?.context_usage?.estimated_tokens,
    ).toBe(200);
    sessionApi.setVisibleSession(null);
    expect(useTurnUsageStore.getState().snapshot).toBeNull();
  });
  it("restores usage when selection hits the preload result cache", async () => {
    const { useTurnUsageStore } = await import("../turnUsageStore");
    vi.spyOn(api, "getChat").mockResolvedValue({
      messages: [
        {
          role: "assistant",
          content: [{ type: "text", text: "done" }],
          metadata: {
            qwenpaw_turn_usage: {
              context_usage: {
                estimated_tokens: 500,
                max_input_length: 100000,
                context_usage_ratio: 0.5,
              },
            },
          },
        },
      ],
      status: "idle",
    } as ChatHistory);
    sessionApi.setVisibleSession(null);
    await sessionApi.preloadSession("cached");
    expect(useTurnUsageStore.getState().snapshot).toBeNull();
    sessionApi.setVisibleSession("cached");
    await sessionApi.getSession("cached");
    expect(
      useTurnUsageStore.getState().snapshot?.context_usage?.estimated_tokens,
    ).toBe(500);
  });
});
