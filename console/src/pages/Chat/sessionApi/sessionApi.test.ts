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
import { createSdkSessionAdapter } from "../sdkSessionAdapter";

const sessionWindow = window as Window & { currentSessionId?: string };

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

describe("createSession owner-epoch singleflight", () => {
  beforeEach(() => {
    sessionApi.resetForTests();
    sessionApi.setActiveAgent("A");
    sessionApi.resetWindowIdentity();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    sessionApi.resetForTests();
    sessionApi.resetWindowIdentity();
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
      const identityBefore = sessionWindow.currentSessionId;
      if (settle === "resolve") old.resolve(createdChat("stale-chat"));
      else old.reject(new Error("old failure"));
      const [stale] = await oldResult;
      expect(stale.status).toBe("rejected");
      if (settle === "resolve" && stale.status === "rejected") {
        expect(stale.reason).toMatchObject({ name: "AbortError" });
      }
      expect(selected).not.toHaveBeenCalled();
      expect(sessionWindow.currentSessionId).toBe(identityBefore);
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
      expect(sessionWindow.currentSessionId).toBe("runtime-fresh-chat");
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
    expect(sessionWindow.currentSessionId).toBe("runtime-fresh-chat");
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
    sessionApi.resetWindowIdentity();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    sessionApi.resetForTests();
    sessionApi.resetWindowIdentity();
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
