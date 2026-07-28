/**
 * Regression tests for the stale-channel identity leak:
 * "After deleting a channel and creating a new agent, the first chat of the
 *  new agent is created on the deleted channel instead of console."
 *
 * Root cause: `window.currentChannel` / `window.currentSessionId` are page
 * globals that are only rewritten when another session loads. After an agent
 * switch they still hold the previous agent's identity, and
 * `getSessionIdentity()` blindly trusted them in its fallback branch, so the
 * first message of a fresh chat could carry a channel that no longer exists.
 *
 * Fix under test:
 *  - `getSessionIdentity()` only trusts the window globals when they resolve
 *    to a session in the current session list; otherwise it falls back to
 *    the console defaults.
 *  - `resetWindowIdentity()` clears the globals (called on agent switch).
 */
import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import type { ChatSpec, ChatHistory, Message } from "../../../api";
import api from "../../../api";
import sessionApi from "../sessionApi";

interface IdentityWindow extends Window {
  currentSessionId?: string;
  currentUserId?: string;
  currentChannel?: string;
}

declare const window: IdentityWindow;

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

/** Loads the given chats into sessionApi and opens the first one so the
 *  window identity globals are populated from it. */
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
  window.currentSessionId = "";
  window.currentUserId = "";
  window.currentChannel = "";
});

afterEach(async () => {
  // Drain the singleton's session list so state never leaks across tests.
  await reloadAsEmptyAgent();
  vi.restoreAllMocks();
});

describe("getSessionIdentity stale-channel fallback", () => {
  it("falls back to console defaults when the window identity no longer matches any session", async () => {
    const spec = makeChatSpec(
      "33333333-3333-4333-8333-333333333333",
      "yuanbao",
      "u1",
    );
    await openChat(spec);

    // Precondition: viewing the yuanbao chat populated the window globals.
    expect(window.currentChannel).toBe("yuanbao");
    expect(window.currentSessionId).toBe("yuanbao:u1");

    // Agent switch: list reloads for the new agent, globals go stale.
    sessionApi.lastActiveChatId = null;
    await reloadAsEmptyAgent();

    const identity = sessionApi.getSessionIdentity();
    expect(identity.channel).toBe("console");
    expect(identity.sessionId).toBe("");
    expect(identity.userId).toBe("default");
  });

  it("keeps trusting the window identity while its session is still in the list", async () => {
    const spec = makeChatSpec(
      "44444444-4444-4444-8444-444444444444",
      "dingtalk",
      "u2",
    );
    await openChat(spec);
    sessionApi.lastActiveChatId = null;

    // Same agent, session still listed: external-channel identity is valid.
    const identity = sessionApi.getSessionIdentity();
    expect(identity.channel).toBe("dingtalk");
    expect(identity.sessionId).toBe("dingtalk:u2");
    expect(identity.userId).toBe("u2");
  });

  it("prefers the lastActiveChatId session over the window globals", async () => {
    const spec = makeChatSpec(
      "55555555-5555-4555-8555-555555555555",
      "feishu",
      "u3",
    );
    await openChat(spec);

    // Stale globals from elsewhere must not win over the active session.
    window.currentSessionId = "yuanbao:gone";
    window.currentChannel = "yuanbao";
    sessionApi.lastActiveChatId = spec.id;

    const identity = sessionApi.getSessionIdentity();
    expect(identity.channel).toBe("feishu");
    expect(identity.sessionId).toBe("feishu:u3");
  });
});

describe("resetWindowIdentity", () => {
  it("clears the window identity globals back to defaults", async () => {
    const spec = makeChatSpec(
      "66666666-6666-4666-8666-666666666666",
      "yuanbao",
      "u4",
    );
    await openChat(spec);
    expect(window.currentChannel).toBe("yuanbao");

    sessionApi.resetWindowIdentity();

    expect(window.currentSessionId).toBe("");
    expect(window.currentUserId).toBe("default");
    expect(window.currentChannel).toBe("console");
  });
});
