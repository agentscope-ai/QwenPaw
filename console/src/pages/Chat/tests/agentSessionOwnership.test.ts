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
import { useSessionListStore } from "../../../stores/sessionListStore";
import { useTurnUsageStore } from "../turnUsageStore";
import type { TurnUsageSnapshot } from "../turnUsage";

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
  status: "idle" | "running" = "idle",
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
    status,
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

// Legacy cached drafts still need ID-resolution coverage. New SDK creation
// obtains the UUID before sending; do not make createChat fake the old contract.
function seedLegacyDraft(id = "1788430000000-legacy1") {
  const legacy = sessionApi as unknown as {
    createEmptySession: (id: string, owner: unknown) => any;
    getActiveOwner: () => unknown;
    sessionList: any[];
  };
  const draft = legacy.createEmptySession(id, legacy.getActiveOwner());
  legacy.sessionList.unshift(draft);
  return { session: draft };
}

beforeEach(() => {
  sessionApi.resetForTests();
  useAgentStore.setState({ lastChatIdByAgent: {} });
  useSessionListStore.setState({ _setLibrarySessions: null });
});

afterEach(() => {
  vi.restoreAllMocks();
  sessionApi.resetForTests();
  useSessionListStore.setState({ _setLibrarySessions: null });
});

describe("agent session ownership epochs", () => {
  it("resolves a backend UUID before exposing a newly created session", async () => {
    const pending = deferred<ChatSpec>();
    const create = vi.spyOn(api, "createChat").mockReturnValue(pending.promise);
    sessionApi.setActiveAgent("agent-a");
    const selected = vi.fn();
    sessionApi.onSessionCreated = selected;
    const result = sessionApi.createSession({ name: "new chat" });
    expect(selected).not.toHaveBeenCalled();
    pending.resolve(makeChatSpec(A_CHAT, "runtime-a"));
    expect((await result).session).toMatchObject({
      id: A_CHAT,
      sessionId: "runtime-a",
    });
    expect(selected).toHaveBeenCalledWith(A_CHAT);
    expect(create).toHaveBeenCalledTimes(1);
  });

  it("rejects a creation result from an old Agent epoch", async () => {
    const pending = deferred<ChatSpec>();
    vi.spyOn(api, "createChat").mockReturnValue(pending.promise);
    sessionApi.setActiveAgent("agent-a");
    const created = vi.fn();
    sessionApi.onSessionCreated = created;
    const result = sessionApi.createSession({});
    sessionApi.setActiveAgent("agent-b");
    pending.resolve(makeChatSpec(A_CHAT, "runtime-a"));
    await expect(result).rejects.toMatchObject({ name: "AbortError" });
    expect(created).not.toHaveBeenCalled();
  });

  it("rejects SDK calls made by an unmounted Agent before starting any request", async () => {
    const listSpy = vi.spyOn(api, "listChats").mockResolvedValue([]);
    const getSpy = vi.spyOn(api, "getChat").mockResolvedValue(makeHistory());
    const deleteSpy = vi
      .spyOn(api, "deleteChat")
      .mockResolvedValue({ success: true, chat_id: A_CHAT });
    sessionApi.setActiveAgent("agent-a");
    const oldSdkApi = sessionApi.bindToOwner();

    // A passive effect may run after the store already selected B. Capturing
    // the owner inside getSession would incorrectly claim this old A call for B.
    sessionApi.setActiveAgent("agent-b");
    expect(await oldSdkApi.getSession(A_CHAT)).toBeUndefined();
    expect(await oldSdkApi.getSessionList()).toEqual([]);
    expect(await oldSdkApi.updateSession({ id: A_CHAT })).toEqual([]);
    expect(await oldSdkApi.removeSession({ id: A_CHAT })).toEqual([]);
    await expect(oldSdkApi.createSession({})).rejects.toMatchObject({
      name: "AbortError",
    });
    expect(listSpy).not.toHaveBeenCalled();
    expect(getSpy).not.toHaveBeenCalled();
    expect(deleteSpy).not.toHaveBeenCalled();

    // Returning to A must not reactivate callbacks from its first mount.
    sessionApi.setActiveAgent("agent-a");
    expect(await oldSdkApi.getSession(A_CHAT)).toBeUndefined();
    expect(getSpy).not.toHaveBeenCalled();
    const currentSdkApi = sessionApi.bindToOwner();
    listSpy.mockResolvedValue([makeChatSpec(A_CHAT, "console:a")]);
    await currentSdkApi.getSessionList();
    expect(await currentSdkApi.getSession(A_CHAT)).toMatchObject({
      id: A_CHAT,
    });
    expect(getSpy).toHaveBeenCalledTimes(1);
  });

  it("requests only host-owned sessions and history in main Chat", async () => {
    const listSpy = vi
      .spyOn(api, "listChats")
      .mockResolvedValue([makeChatSpec(A_CHAT, "console:a")]);
    const getSpy = vi.spyOn(api, "getChat").mockResolvedValue(makeHistory());
    sessionApi.setActiveAgent("agent-a");

    await sessionApi.getSessionList();
    await sessionApi.getSession(A_CHAT);

    expect(listSpy).toHaveBeenCalledWith({
      archived: false,
      include_app_owned: false,
    });
    expect(getSpy).toHaveBeenCalledWith(A_CHAT, {
      signal: undefined,
      include_app_owned: false,
    });
  });

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
    const created = seedLegacyDraft();
    const tempId = created.session.id;
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
    const created = seedLegacyDraft();
    const tempId = created.session.id;
    listSpy.mockResolvedValueOnce([
      makeChatSpec(B_CHAT, tempId),
      makeChatSpec(A_CHAT, "console:a"),
    ]);
    sessionApi.triggerResolve(tempId);
    await flush();
    expect(onSessionIdResolved).toHaveBeenCalledWith(tempId, B_CHAT);
  });

  it("keeps the created UUID stable when sidebar polling observes the new Chat", async () => {
    const chat = makeChatSpec(A_CHAT, "runtime-created");
    vi.spyOn(api, "createChat").mockResolvedValue(chat);
    vi.spyOn(api, "listChats").mockResolvedValue([chat]);
    const onResolved = vi.fn();
    sessionApi.onSessionIdResolved = onResolved;
    sessionApi.setActiveAgent("agent-a");
    const created = await sessionApi.createSession({});
    await sessionApi.getSessionList();
    sessionApi.triggerResolve(created.session.id);
    await flush();
    expect(created.session.id).toBe(A_CHAT);
    expect(sessionApi.getBackendSessionId(A_CHAT)).toBe("runtime-created");
    expect(onResolved).not.toHaveBeenCalled();
  });

  it("does not transfer a resolved local ID to another user sharing the runtime", async () => {
    const listSpy = vi.spyOn(api, "listChats");
    sessionApi.setActiveAgent("agent-a");
    const created = seedLegacyDraft();
    const localId = created.session.id;
    const chatA = makeChatSpec(A_CHAT, localId);
    listSpy.mockResolvedValue([chatA]);
    sessionApi.triggerResolve(localId);
    await flush();
    listSpy.mockResolvedValue([
      chatA,
      { ...makeChatSpec(B_CHAT, localId), user_id: "another-user" },
    ]);
    const sessions = await sessionApi.getSessionList();
    expect(sessions.find((item) => item.id === B_CHAT)).toBeDefined();
    expect(sessionApi.getRealIdForSession(localId)).toBe(A_CHAT);
  });

  it("keeps both legacy generating sessions selectable after resolving their ids", async () => {
    const listSpy = vi.spyOn(api, "listChats");
    const setLibrarySessions = vi.fn();
    useSessionListStore.setState({ _setLibrarySessions: setLibrarySessions });

    sessionApi.setActiveAgent("agent-a");
    const firstTempId = seedLegacyDraft("1788430000000-legacy1").session.id;

    listSpy.mockResolvedValueOnce([
      makeChatSpec(A_CHAT, firstTempId, "chat-1", "running"),
    ]);
    sessionApi.triggerResolve(firstTempId);
    await flush();

    const secondTempId = seedLegacyDraft("1788430000001-legacy2").session.id;

    listSpy.mockResolvedValueOnce([
      makeChatSpec(B_CHAT, secondTempId, "chat-2", "running"),
      makeChatSpec(A_CHAT, firstTempId, "chat-1", "running"),
    ]);
    sessionApi.triggerResolve(secondTempId);
    await flush();

    const latestSessions =
      setLibrarySessions.mock.calls[
        setLibrarySessions.mock.calls.length - 1
      ][0];
    expect(latestSessions).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ id: firstTempId, realId: A_CHAT }),
        expect.objectContaining({ id: secondTempId, realId: B_CHAT }),
      ]),
    );
  });

  it("a stale getSession cannot rewrite window identity, turn usage, or fire selection", async () => {
    vi.spyOn(api, "listChats").mockResolvedValue([
      makeChatSpec(A_CHAT, "console:a"),
    ]);
    const dChat = deferred<ChatHistory>();
    vi.spyOn(api, "getChat").mockReturnValueOnce(dChat.promise);
    const onSessionSelected = vi.fn();
    sessionApi.onSessionSelected = onSessionSelected;

    sessionApi.setActiveAgent("agent-a");
    await sessionApi.getSessionList();
    const pending = sessionApi.getSession(A_CHAT);

    // Switch to B and mark B's current view state with sentinels.
    sessionApi.setActiveAgent("agent-b");
    (window as { currentSessionId?: string }).currentSessionId =
      "sentinel-session";
    const sentinelSnapshot = {
      usage: null,
      context_usage: null,
    } as unknown as TurnUsageSnapshot;
    useTurnUsageStore.getState().setSnapshot(sentinelSnapshot);

    // A's fetch completes late: B's view state must stay untouched.
    dChat.resolve(makeHistory());
    await pending;

    expect((window as { currentSessionId?: string }).currentSessionId).toBe(
      "sentinel-session",
    );
    expect(useTurnUsageStore.getState().snapshot).toBe(sentinelSnapshot);
    expect(onSessionSelected).not.toHaveBeenCalled();
  });

  it("in-flight session requests and preload results are not reused across epochs", async () => {
    vi.spyOn(api, "listChats").mockResolvedValue([
      makeChatSpec(A_CHAT, "console:a"),
    ]);
    const dA = deferred<ChatHistory>();
    const getChatSpy = vi
      .spyOn(api, "getChat")
      .mockReturnValueOnce(dA.promise)
      .mockResolvedValue(makeHistory());

    // A preloads; the fetch is still pending when the agent switches.
    sessionApi.setActiveAgent("agent-a");
    await sessionApi.getSessionList();
    const preloadPromise = sessionApi.preloadSession(A_CHAT);

    // B requests the same id: it must start its own fetch instead of
    // adopting A's in-flight request (and A's captured owner).
    sessionApi.setActiveAgent("agent-b");
    await sessionApi.getSessionList();
    await sessionApi.getSession(A_CHAT);
    expect(getChatSpy).toHaveBeenCalledTimes(2);

    // A's preload completes late: it must fail like an aborted request so
    // the caller's navigation path never runs, and its result must not be
    // served from the short-lived result cache.
    dA.resolve(makeHistory());
    await expect(preloadPromise).rejects.toMatchObject({
      name: "AbortError",
    });
  });

  it("a stale preload that fails with a normal error still rejects as AbortError", async () => {
    vi.spyOn(api, "listChats").mockResolvedValue([
      makeChatSpec(A_CHAT, "console:a"),
    ]);
    const dChat = deferred<ChatHistory>();
    vi.spyOn(api, "getChat").mockReturnValueOnce(dChat.promise);

    // Agent A starts a preload whose fetch is still pending at switch time.
    sessionApi.setActiveAgent("agent-a");
    await sessionApi.getSessionList();
    const preloadPromise = sessionApi.preloadSession(A_CHAT);

    // After the switch the old request fails with a plain backend error.
    // The caller must see an abort — a normal rejection would be handled as
    // a current-switch failure and select the stale session.
    sessionApi.setActiveAgent("agent-b");
    dChat.reject(new Error("backend unavailable"));

    await expect(preloadPromise).rejects.toMatchObject({
      name: "AbortError",
    });
  });

  it("switching agents releases a stuck session-switch lock", () => {
    sessionApi.setActiveAgent("agent-a");
    // Simulate an embedded switch whose finally never ran (unmount abort).
    sessionApi.isSessionSwitching = true;

    sessionApi.setActiveAgent("agent-b");

    expect(sessionApi.isSessionSwitching).toBe(false);
  });

  it("the previous agent's list entries cannot leak ids into the new agent's list", async () => {
    const listSpy = vi.spyOn(api, "listChats");

    // Agent A resolves a blank local session to its backend UUID, leaving a
    // list entry with a local id and realId mapping.
    sessionApi.setActiveAgent("agent-a");
    const created = seedLegacyDraft();
    const tempId = created.session.id;
    listSpy.mockResolvedValueOnce([makeChatSpec(A_CHAT, tempId)]);
    sessionApi.triggerResolve(tempId);
    await flush();

    // Agent B's backend chat shares the same session_id (channel:user_id).
    // Merging against A's leftover entry would transfer A's local id and
    // UUID onto B's chat.
    sessionApi.setActiveAgent("agent-b");
    listSpy.mockResolvedValueOnce([makeChatSpec(B_CHAT, tempId)]);
    const list = await sessionApi.getSessionList();

    expect(list).toHaveLength(1);
    expect(list[0].id).toBe(B_CHAT);
    expect((list[0] as { realId?: string }).realId).toBeUndefined();
  });

  it("work started before the first ownership claim is rejected after it", async () => {
    // Return to the pristine unclaimed state (the store subscription claims
    // the persisted agent as soon as beforeEach touches the agent store).
    sessionApi.resetForTests();

    // A sidebar-style preload starts while ownership is still unclaimed.
    const dList = deferred<ChatSpec[]>();
    const listSpy = vi.spyOn(api, "listChats");
    listSpy.mockReturnValueOnce(dList.promise);
    const pUnclaimed = sessionApi.getSessionList();

    // The first claim arrives (e.g. the app resolves the selected agent).
    sessionApi.setActiveAgent("agent-a");

    dList.resolve([makeChatSpec(A_CHAT, "console:a")]);
    const stale = await pUnclaimed;
    expect(stale).toEqual([]);

    // The claimed epoch loads its own list normally.
    listSpy.mockResolvedValueOnce([makeChatSpec(B_CHAT, "console:b")]);
    const fresh = await sessionApi.getSessionList();
    expect(fresh.map((s) => s.id)).toEqual([B_CHAT]);
  });
});
