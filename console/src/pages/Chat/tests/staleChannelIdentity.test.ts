/**
 * Regression tests for stale channel identity. Identity must be resolved from
 * an explicit session reference, never from mutable window globals.
 */
import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import type { ChatSpec, ChatHistory, Message } from "../../../api";
import api from "../../../api";
import sessionApi from "../sessionApi";

const T0 = "2026-07-20T10:00:00.000000+00:00";

function makeChatSpec(id: string, channel: string, userId: string): ChatSpec {
  return {
    id,
    name: `${channel} chat`,
    session_id: `${channel}:${userId}`,
    user_id: userId,
    channel,
    created_at: T0,
    updated_at: T0,
    meta: {},
    status: "idle",
    pinned: false,
    archived: false,
    archived_at: null,
  } as unknown as ChatSpec;
}

function makeHistory(): ChatHistory {
  const messages: Message[] = [
    {
      role: "assistant",
      content: [{ type: "text", text: "hello" }],
    } as unknown as Message,
  ];
  return { messages, status: "idle" } as unknown as ChatHistory;
}

/** Loads the given chat into sessionApi. */
async function openChat(spec: ChatSpec): Promise<void> {
  vi.spyOn(api, "listChats").mockResolvedValue([spec]);
  vi.spyOn(api, "getChat").mockResolvedValue(makeHistory());
  await sessionApi.getSessionList();
  await sessionApi.getSession(spec.id);
}

/** Simulates the session-list reload that happens after an agent switch:
 *  the new agent owns none of the previous agent's chats. */
async function reloadAsEmptyAgent(): Promise<void> {
  vi.spyOn(api, "listChats").mockResolvedValue([]);
  await sessionApi.getSessionList();
}

beforeEach(() => {
  sessionApi.lastActiveChatId = null;
});

afterEach(async () => {
  // Drain the singleton's session list so state never leaks across tests.
  await reloadAsEmptyAgent();
  vi.restoreAllMocks();
});

describe("getSessionIdentity", () => {
  it("falls back to console defaults when the explicit session is unknown", async () => {
    const spec = makeChatSpec(
      "33333333-3333-4333-8333-333333333333",
      "yuanbao",
      "u1",
    );
    await openChat(spec);

    await reloadAsEmptyAgent();

    const identity = sessionApi.getSessionIdentity(spec.id);
    expect(identity.channel).toBe("console");
    expect(identity.sessionId).toBe("");
    expect(identity.userId).toBe("default");
  });

  it("resolves user and channel from an explicit chat id", async () => {
    const spec = makeChatSpec(
      "44444444-4444-4444-8444-444444444444",
      "dingtalk",
      "u2",
    );
    await openChat(spec);
    const identity = sessionApi.getSessionIdentity(spec.id);
    expect(identity.channel).toBe("dingtalk");
    expect(identity.sessionId).toBe("dingtalk:u2");
    expect(identity.userId).toBe("u2");
  });

  it("also resolves an explicit runtime session id", async () => {
    const spec = makeChatSpec(
      "55555555-5555-4555-8555-555555555555",
      "feishu",
      "u3",
    );
    await openChat(spec);

    const identity = sessionApi.getSessionIdentity("feishu:u3");
    expect(identity.channel).toBe("feishu");
    expect(identity.sessionId).toBe("feishu:u3");
    expect(identity.chatId).toBe(spec.id);
  });
});
