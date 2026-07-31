/**
 * Pending user message must survive the "generation finished but memory
 * not yet flushed" window.
 *
 * customFetch caches the last user message in sessionStorage
 * (setLastUserMessage) so patchLastUserMessage can re-insert it when the
 * chat page remounts (mode switch /chat <-> /coding, session switch) while
 * the backend has not persisted the turn yet.
 *
 * The old behavior cleared the cache unconditionally whenever the chat
 * reported status != "running". Two windows made that lossy:
 *   - POST sent but the tracker has not registered the run yet
 *     (status still "idle"),
 *   - generation completed but the agent memory flush has not finished,
 *     so the fetched history is missing the final turn.
 * In both cases the last user message disappeared permanently.
 *
 * New semantics: on idle, clear the cache only when the fetched history
 * already contains the pending text; otherwise patch the message in and
 * keep the cache for the next confirmation.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import type { Message, ChatHistory } from "../../../api/types/chat";

vi.mock("../../../api/modules/chat", async (importOriginal) => {
  const actual = await importOriginal<
    typeof import("../../../api/modules/chat")
  >();
  return {
    ...actual,
    chatApi: {
      ...actual.chatApi,
      filePreviewUrl: vi.fn(
        (p: string) => `http://localhost:8000/files/preview/${p}`,
      ),
    },
  };
});

// Import AFTER mocks are registered.
import sessionApi from "../sessionApi";
import {
  attachClientMessageId,
  QWENPAW_CLIENT_MESSAGE_ID_KEY,
} from "../../../utils/clientMessageId";

const STORAGE_PREFIX = "qwenpaw_pending_user_msg_";

interface SessionApiTestAccess {
  sessionList: Array<Record<string, unknown>>;
  convertedSessionCache: Map<unknown, unknown>;
  sessionResultCache: Map<unknown, unknown>;
  sessionRequests: Map<unknown, unknown>;
  lastSelectedIds: Set<unknown>;
}

interface RuntimeContent {
  type?: string;
  text?: string;
}

interface RuntimeMessage {
  role?: string;
  cards?: Array<{
    data?: {
      input?: Array<{ content?: RuntimeContent[] }>;
    };
  }>;
}

interface RuntimeSession {
  messages: RuntimeMessage[];
}

const testApi = sessionApi as unknown as SessionApiTestAccess;

function userMsg(id: string, text: string, clientMessageId?: string): Message {
  return {
    id,
    role: "user",
    content: [{ type: "text", text }],
    metadata: {
      timestamp: "2026-06-01 10:00:00.000",
      ...(clientMessageId
        ? {
            metadata: {
              [QWENPAW_CLIENT_MESSAGE_ID_KEY]: clientMessageId,
            },
          }
        : {}),
    },
  } as Message;
}

function assistantMsg(id: string, text: string): Message {
  return {
    id,
    role: "assistant",
    content: [{ type: "text", text }],
    metadata: { timestamp: "2026-06-01 10:00:01.000" },
  } as Message;
}

function seedSessionList(id: string): void {
  testApi.sessionList = [
    { id, sessionId: id, userId: "u", channel: "c", name: "t" },
  ];
}

async function mockGetChat(history: ChatHistory) {
  const apiImport = await import("../../../api");
  return vi.spyOn(apiImport.api, "getChat").mockResolvedValue(history);
}

/** Collect texts of user-role cards from a converted session. */
function userCardTexts(session: unknown): string[] {
  const msgs = (session as RuntimeSession).messages;
  return msgs
    .filter((m) => m.role === "user")
    .map((m) => {
      const content = m.cards?.[0]?.data?.input?.[0]?.content;
      return Array.isArray(content)
        ? content
            .filter((c) => c.type === "text")
            .map((c) => c.text)
            .join("\n")
        : "";
    });
}

describe("patchLastUserMessage — pending cache lifecycle", () => {
  beforeEach(() => {
    testApi.sessionList = [];
    testApi.convertedSessionCache.clear();
    testApi.sessionResultCache.clear();
    testApi.sessionRequests.clear();
    testApi.lastSelectedIds.clear();
    sessionStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    sessionStorage.clear();
  });

  it("patches the pending user message while generating (status running)", async () => {
    seedSessionList("chat-running");
    sessionApi.setLastUserMessage("chat-running", "hello in flight");
    await mockGetChat({
      messages: [userMsg("u1", "earlier"), assistantMsg("a1", "reply")],
      status: "running",
    } as ChatHistory);

    const session = await sessionApi.getSession("chat-running");
    expect(userCardTexts(session)).toContain("hello in flight");
    // Cache is kept while the turn is still generating.
    expect(sessionStorage.getItem(`${STORAGE_PREFIX}chat-running`)).not.toBe(
      null,
    );
  });

  it("attaches the client id without dropping existing metadata", () => {
    expect(
      attachClientMessageId(
        { role: "user", metadata: { source: "sdk" } },
        "client-new",
      ),
    ).toEqual({
      role: "user",
      metadata: {
        source: "sdk",
        [QWENPAW_CLIENT_MESSAGE_ID_KEY]: "client-new",
      },
    });
  });

  it("discards only the pending message owned by the failed request", () => {
    sessionApi.setLastUserMessage(
      "chat-failed",
      "newer request",
      undefined,
      "client-new",
    );

    sessionApi.discardLastUserMessage("chat-failed", "client-old");
    expect(sessionStorage.getItem(`${STORAGE_PREFIX}chat-failed`)).not.toBe(
      null,
    );

    sessionApi.discardLastUserMessage("chat-failed", "client-new");
    expect(sessionStorage.getItem(`${STORAGE_PREFIX}chat-failed`)).toBe(null);
  });

  it("clears the cache on idle when history already contains the text", async () => {
    seedSessionList("chat-done");
    sessionApi.setLastUserMessage("chat-done", "persisted question");
    await mockGetChat({
      messages: [
        userMsg("u1", "persisted question"),
        assistantMsg("a1", "final answer"),
      ],
      status: "idle",
    } as ChatHistory);

    const session = await sessionApi.getSession("chat-done");
    const texts = userCardTexts(session);
    // No duplicate user card.
    expect(texts.filter((t) => t.includes("persisted question"))).toHaveLength(
      1,
    );
    expect(sessionStorage.getItem(`${STORAGE_PREFIX}chat-done`)).toBe(null);
  });

  it("keeps the cache and patches the message on idle when history is missing it (flush window)", async () => {
    seedSessionList("chat-window");
    sessionApi.setLastUserMessage("chat-window", "lost in the window");
    await mockGetChat({
      messages: [
        userMsg("u1", "old question"),
        assistantMsg("a1", "old answer"),
      ],
      status: "idle",
    } as ChatHistory);

    const session = await sessionApi.getSession("chat-window");
    // The pending message must still be visible after the remount…
    expect(userCardTexts(session)).toContain("lost in the window");
    // …and the cache must survive until history confirms persistence.
    expect(sessionStorage.getItem(`${STORAGE_PREFIX}chat-window`)).not.toBe(
      null,
    );
  });

  it("does nothing on idle when no pending message is cached", async () => {
    seedSessionList("chat-clean");
    const getChat = await mockGetChat({
      messages: [userMsg("u1", "q"), assistantMsg("a1", "a")],
      status: "idle",
    } as ChatHistory);

    const session = await sessionApi.getSession("chat-clean");
    expect(userCardTexts(session)).toEqual(["q"]);
    expect(getChat).toHaveBeenCalledTimes(1);
  });

  it("does not clear the cache when the pending text is a substring of an older message", async () => {
    // "yes" is contained in "yesterday what happened" — substring
    // matching would wrongly treat the new turn as persisted and drop
    // the pending instruction. Only a normalized full match may clear.
    seedSessionList("chat-substr");
    sessionApi.setLastUserMessage("chat-substr", "yes");
    await mockGetChat({
      messages: [
        userMsg("u1", "yesterday what happened"),
        assistantMsg("a1", "an answer"),
      ],
      status: "idle",
    } as ChatHistory);

    const session = await sessionApi.getSession("chat-substr");
    expect(userCardTexts(session)).toContain("yes");
    expect(sessionStorage.getItem(`${STORAGE_PREFIX}chat-substr`)).not.toBe(
      null,
    );
  });

  it("keeps an identical pending prompt when its client id is newer", async () => {
    seedSessionList("chat-repeat");
    sessionApi.setLastUserMessage(
      "chat-repeat",
      "continue",
      undefined,
      "client-new",
    );
    await mockGetChat({
      messages: [
        userMsg("u1", "continue", "client-old"),
        assistantMsg("a1", "previous answer"),
      ],
      status: "idle",
    } as ChatHistory);

    const session = await sessionApi.getSession("chat-repeat");
    expect(userCardTexts(session)).toEqual(["continue", "continue"]);
    expect(sessionStorage.getItem(`${STORAGE_PREFIX}chat-repeat`)).not.toBe(
      null,
    );
  });

  it("clears an identical pending prompt only when its client id matches", async () => {
    seedSessionList("chat-repeat-confirmed");
    sessionApi.setLastUserMessage(
      "chat-repeat-confirmed",
      "continue",
      undefined,
      "client-new",
    );
    await mockGetChat({
      messages: [
        userMsg("u1", "continue", "client-new"),
        assistantMsg("a1", "latest answer"),
      ],
      status: "idle",
    } as ChatHistory);

    const session = await sessionApi.getSession("chat-repeat-confirmed");
    expect(userCardTexts(session)).toEqual(["continue"]);
    expect(
      sessionStorage.getItem(`${STORAGE_PREFIX}chat-repeat-confirmed`),
    ).toBe(null);
  });

  it("does not serve a patched (incomplete) idle history from the LRU cache", async () => {
    // The patched history is missing the agent reply that has not been
    // flushed yet. Caching it would keep serving the incomplete turn
    // for up to the cache TTL; every switch-back must refetch until the
    // backend history confirms the pending text.
    seedSessionList("chat-nocache");
    sessionApi.setLastUserMessage("chat-nocache", "unconfirmed turn");
    const getChat = await mockGetChat({
      messages: [userMsg("u1", "old q"), assistantMsg("a1", "old a")],
      status: "idle",
    } as ChatHistory);

    await sessionApi.getSession("chat-nocache");
    testApi.sessionResultCache.clear();
    testApi.lastSelectedIds.clear();
    await sessionApi.getSession("chat-nocache");
    expect(getChat).toHaveBeenCalledTimes(2);
  });

  it("still caches idle sessions once the pending text is confirmed", async () => {
    seedSessionList("chat-confirmed");
    sessionApi.setLastUserMessage("chat-confirmed", "the question");
    const getChat = await mockGetChat({
      messages: [
        userMsg("u1", "the question"),
        assistantMsg("a1", "the answer"),
      ],
      status: "idle",
    } as ChatHistory);

    await sessionApi.getSession("chat-confirmed");
    testApi.sessionResultCache.clear();
    testApi.lastSelectedIds.clear();
    await sessionApi.getSession("chat-confirmed");
    // Second call is served from the LRU cache — history was complete.
    expect(getChat).toHaveBeenCalledTimes(1);
  });
});
