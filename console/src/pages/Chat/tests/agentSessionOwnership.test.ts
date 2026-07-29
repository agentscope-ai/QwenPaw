/**
 * Regression tests for cross-agent session ownership.
 *
 * SessionApi is a page-global singleton: its session list, in-flight list
 * request, and temporary-ID resolution are not naturally scoped to an agent.
 * Without ownership tracking, an asynchronous operation started under agent A
 * could finish after the user switched to agent B and then replace B's
 * session list, navigate B's view, or persist A's chat id for B.
 *
 * These tests drive the public sessionApi surface with deferred `api`
 * promises to prove that late results from a stale ownership epoch are
 * rejected, while same-epoch results keep working.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import type { ChatSpec, ChatHistory } from "../../../api";
import api from "../../../api";
import sessionApi from "../sessionApi";
import { useAgentStore } from "../../../stores/agentStore";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

/** Flush pending microtasks so `.then` chains after a resolve can settle. */
async function flush(): Promise<void> {
  await new Promise((res) => setTimeout(res, 0));
}

function makeChatSpec(
  id: string,
  sessionId: string,
  name = "chat",
): ChatSpec {
  return {
    id,
    name,
    session_id: sessionId,
    user_id: "default",
    channel: "console",
    created_at: "2026-07-27T10:00:00.000000+00:00",
    updated_at: "2026-07-27T10:00:00.000000+00:00",
    meta: {},
    status: "idle",
    pinned: false,
    archived: false,
    archived_at: null,
  } as unknown as ChatSpec;
}

function makeHistory(): ChatHistory {
  return { messages: [], status: "idle" } as unknown as ChatHistory;
}

const A_CHAT = "11111111-aaaa-4aaa-8aaa-111111111111";
const B_CHAT = "22222222-bbbb-4bbb-8bbb-222222222222";

beforeEach(() => {
  sessionApi.resetForTests();
  useAgentStore.setState({ lastChatIdByAgent: {} });
});

afterEach(() => {
  vi.restoreAllMocks();
  sessionApi.resetForTests();
});

describe("agent session ownership epochs", () => {
  it("Test A: an old agent's list request cannot replace the new agent's list", async () => {
    const listSpy = vi.spyOn(api, "listChats");
    const onSessionSelected = vi.fn();
    sessionApi.onSessionSelected = onSessionSelected;

    // Agent A starts a list request that stays pending.
    sessionApi.setActiveAgent("agent-a");
    const dA = deferred<ChatSpec[]>();
    listSpy.mockReturnValueOnce(dA.promise);
    const pA = sessionApi.getSessionList();

    // The user switches to agent B, whose own request resolves first.
    sessionApi.setActiveAgent("agent-b");
    const dB = deferred<ChatSpec[]>();
    listSpy.mockReturnValueOnce(dB.promise);
    const pB = sessionApi.getSessionList();

    // B must not have reused A's in-flight promise.
    expect(pB).not.toBe(pA);
    expect(listSpy).toHaveBeenCalledTimes(2);

    dB.resolve([makeChatSpec(B_CHAT, "console:b")]);
    const listB = await pB;
    expect(listB.map((s) => s.id)).toEqual([B_CHAT]);

    // A's request finishes late: its data must not be applied.
    dA.resolve([makeChatSpec(A_CHAT, "console:a")]);
    const staleResult = await pA;
    expect(staleResult.map((s) => s.id)).toEqual([B_CHAT]);

    // A fresh call still sees B's list, not A's.
    listSpy.mockResolvedValueOnce([makeChatSpec(B_CHAT, "console:b")]);
    const current = await sessionApi.getSessionList();
    expect(current.map((s) => s.id)).toEqual([B_CHAT]);
    expect(onSessionSelected).not.toHaveBeenCalled();
  });

  it("Test B: an old temp-id resolution cannot notify or persist for the new agent", async () => {
    const listSpy = vi.spyOn(api, "listChats");
    const onSessionIdResolved = vi.fn();
    sessionApi.onSessionIdResolved = onSessionIdResolved;
    useAgentStore.setState({ lastChatIdByAgent: { "agent-b": B_CHAT } });

    // Agent A creates a blank local session (temp timestamp id).
    sessionApi.setActiveAgent("agent-a");
    const spec: { id?: string } = {};
    await sessionApi.createSession(spec);
    const tempId = spec.id!;
    expect(tempId).toMatch(/^\d+-[a-z0-9]+$/);

    // First message sent: resolution starts but the list stays pending.
    const dResolve = deferred<ChatSpec[]>();
    listSpy.mockReturnValueOnce(dResolve.promise);
    sessionApi.triggerResolve(tempId);

    // The user switches to agent B before A's resolution completes.
    sessionApi.setActiveAgent("agent-b");

    // A's backend answer arrives with the matching chat (session_id equals
    // the temp id, which would resolve successfully in the same epoch).
    dResolve.resolve([makeChatSpec(A_CHAT, tempId)]);
    await flush();

    // No notification reaches B's view and B's persisted chat is untouched.
    expect(onSessionIdResolved).not.toHaveBeenCalled();
    expect(useAgentStore.getState().getLastChatId("agent-b")).toBe(B_CHAT);
  });

  it("Test C: A -> B -> A rejects results from the first A epoch", async () => {
    const listSpy = vi.spyOn(api, "listChats");

    // Work starts under the first A epoch.
    sessionApi.setActiveAgent("agent-a");
    const dOld = deferred<ChatSpec[]>();
    listSpy.mockReturnValueOnce(dOld.promise);
    const pOld = sessionApi.getSessionList();

    // Switch away and back: the agent id matches again but the epoch differs.
    sessionApi.setActiveAgent("agent-b");
    sessionApi.setActiveAgent("agent-a");
    const dNew = deferred<ChatSpec[]>();
    listSpy.mockReturnValueOnce(dNew.promise);
    const pNew = sessionApi.getSessionList();
    dNew.resolve([makeChatSpec(B_CHAT, "console:new-a")]);
    await pNew;

    // The generation-1 work resolves last and must still be rejected.
    dOld.resolve([makeChatSpec(A_CHAT, "console:old-a")]);
    const staleResult = await pOld;
    expect(staleResult.map((s) => s.id)).toEqual([B_CHAT]);
  });

  it("Test D: same-owner list, selection, and temp-id resolution still work", async () => {
    const listSpy = vi.spyOn(api, "listChats");
    vi.spyOn(api, "getChat").mockResolvedValue(makeHistory());
    const onSessionSelected = vi.fn();
    const onSessionIdResolved = vi.fn();
    sessionApi.onSessionSelected = onSessionSelected;
    sessionApi.onSessionIdResolved = onSessionIdResolved;

    sessionApi.setActiveAgent("agent-a");

    // List loading applies normally.
    listSpy.mockResolvedValueOnce([makeChatSpec(A_CHAT, "console:a")]);
    const list = await sessionApi.getSessionList();
    expect(list.map((s) => s.id)).toEqual([A_CHAT]);

    // Session loading notifies selection normally.
    await sessionApi.getSession(A_CHAT);
    expect(onSessionSelected).toHaveBeenCalledWith(A_CHAT, null);

    // Temp-id resolution completes normally within the same epoch. The
    // backend reports the new chat with session_id equal to the temp id.
    const spec: { id?: string } = {};
    await sessionApi.createSession(spec);
    const tempId = spec.id!;
    listSpy.mockResolvedValueOnce([
      makeChatSpec(B_CHAT, tempId),
      makeChatSpec(A_CHAT, "console:a"),
    ]);
    sessionApi.triggerResolve(tempId);
    await flush();
    expect(onSessionIdResolved).toHaveBeenCalledWith(tempId, B_CHAT);
  });
});
