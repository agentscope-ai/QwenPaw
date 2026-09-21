import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ChatHistory, Message } from "../../../api/types/chat";

vi.mock("../../../api/modules/chat", async (importOriginal) => {
  const actual = await importOriginal<
    typeof import("../../../api/modules/chat")
  >();
  return {
    ...actual,
    chatApi: {
      ...actual.chatApi,
      filePreviewUrl: vi.fn(
        (path: string) => `http://localhost:8000/files/preview/${path}`,
      ),
    },
  };
});

import sessionApi from "../sessionApi";

interface SessionApiTestAccess {
  convertedSessionCache: Map<unknown, unknown>;
  lastSelectedIds: Set<unknown>;
  sessionList: Array<Record<string, unknown>>;
  sessionRequests: Map<unknown, unknown>;
  sessionResultCache: Map<unknown, unknown>;
}

interface RuntimeSession {
  messages: Array<{
    role?: string;
    cards?: Array<{
      data?: {
        input?: Array<{ content?: Array<{ type?: string; text?: string }> }>;
      };
    }>;
  }>;
}

const testApi = sessionApi as unknown as SessionApiTestAccess;
const legacyPendingKey = "qwenpaw_pending_user_msg_chat-running";

function userMessage(id: string, text: string): Message {
  return {
    id,
    role: "user",
    content: [{ type: "text", text }],
    metadata: { timestamp: "2026-09-21T00:00:00Z" },
  } as Message;
}

function userTexts(session: unknown): string[] {
  return (session as RuntimeSession).messages
    .filter((message) => message.role === "user")
    .map((message) =>
      (message.cards?.[0]?.data?.input?.[0]?.content ?? [])
        .filter((content) => content.type === "text")
        .map((content) => content.text ?? "")
        .join("\n"),
    );
}

describe("backend-authoritative user history", () => {
  beforeEach(() => {
    testApi.sessionList = [
      {
        id: "chat-running",
        sessionId: "chat-running",
        userId: "u",
        channel: "console",
        name: "test",
      },
    ];
    testApi.convertedSessionCache.clear();
    testApi.sessionResultCache.clear();
    testApi.sessionRequests.clear();
    testApi.lastSelectedIds.clear();
    localStorage.clear();
    sessionStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
    sessionStorage.clear();
  });

  it("ignores legacy pending storage while a chat is running", async () => {
    localStorage.setItem(
      legacyPendingKey,
      JSON.stringify({ text: "/compact", clientMessageId: "client-1" }),
    );
    const apiImport = await import("../../../api");
    vi.spyOn(apiImport.api, "getChat").mockResolvedValue({
      messages: [userMessage("backend-user", "persisted input")],
      status: "running",
    } as ChatHistory);

    const session = await sessionApi.getSession("chat-running");

    expect(userTexts(session)).toEqual(["persisted input"]);
    expect(userTexts(session)).not.toContain("/compact");
    expect(localStorage.getItem(legacyPendingKey)).toBeNull();
  });

  it("does not append a user card missing from the transcript", async () => {
    localStorage.setItem(
      legacyPendingKey,
      JSON.stringify({ text: "/compact", clientMessageId: "client-2" }),
    );
    const apiImport = await import("../../../api");
    vi.spyOn(apiImport.api, "getChat").mockResolvedValue({
      messages: [],
      status: "idle",
    } as ChatHistory);

    const session = await sessionApi.getSession("chat-running");

    expect(userTexts(session)).toEqual([]);
    expect(localStorage.getItem(legacyPendingKey)).toBeNull();
  });
});
