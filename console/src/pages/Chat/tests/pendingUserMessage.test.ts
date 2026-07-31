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

const STORAGE_PREFIX = "qwenpaw_pending_user_msg_";

function userMsg(id: string, text: string): Message {
  return {
    id,
    role: "user",
    content: [{ type: "text", text }],
    metadata: { timestamp: "2026-06-01 10:00:00.000" },
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
  (sessionApi as any).sessionList = [
    { id, sessionId: id, userId: "u", channel: "c", name: "t" },
  ];
}

async function mockGetChat(history: ChatHistory) {
  const apiImport = await import("../../../api");
  return vi.spyOn(apiImport.api, "getChat").mockResolvedValue(history);
}

/** Collect texts of user-role cards from a converted session. */
function userCardTexts(session: unknown): string[] {
  const msgs = (session as { messages: any[] }).messages;
  return msgs
    .filter((m) => m.role === "user")
    .map((m) => {
      const content = m.cards?.[0]?.data?.input?.[0]?.content;
      return Array.isArray(content)
        ? content
            .filter((c: any) => c.type === "text")
            .map((c: any) => c.text)
            .join("\n")
        : "";
    });
}

describe("patchLastUserMessage — pending cache lifecycle", () => {
  beforeEach(() => {
    (sessionApi as any).sessionList = [];
    (sessionApi as any).convertedSessionCache.clear();
    (sessionApi as any).sessionResultCache.clear();
    (sessionApi as any).sessionRequests.clear();
    (sessionApi as any).lastSelectedIds.clear();
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
});
