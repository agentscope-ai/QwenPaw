import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import api, { type ChatHistory, type ChatSpec } from "../../../api";
import { ApiError } from "../../../api/request";
import { menuRegistry } from "../../../plugins/registry/store";
import { useAgentStore } from "../../../stores/agentStore";
import {
  syncSessionsGlobal,
  useSessionListStore,
} from "../../../stores/sessionListStore";
import sessionApi from "../sessionApi";
import { useChatRouteResolution } from "./useChatRouteResolution";

const TARGET = "22222222-2222-4222-8222-222222222222";

function chat(id = TARGET): ChatSpec {
  return {
    id,
    name: "Target conversation",
    session_id: `runtime-${id}`,
    user_id: "target-user",
    channel: "console",
    created_at: null,
    updated_at: null,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}

function mount(referenceId?: string) {
  return renderHook(
    ({ referenceId }: { referenceId?: string }) => {
      const { selectedAgent } = useAgentStore();
      return useChatRouteResolution(referenceId, selectedAgent);
    },
    { initialProps: { referenceId } },
  );
}

beforeEach(() => {
  sessionApi.resetForTests();
  useSessionListStore.setState({ sessions: [], _setLibrarySessions: null });
  useAgentStore.setState({ selectedAgent: "a", lastChatIdByAgent: {} });
  vi.spyOn(menuRegistry, "refresh").mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("chat route ownership resolution", () => {
  it("activates a same-agent cold link before the session list arrives", async () => {
    const resolve = vi.spyOn(api, "resolveChat").mockResolvedValue({
      agent_id: "a",
      chat: chat(),
    });
    const { result } = mount(TARGET);

    expect(result.current.blocked).toBe(true);
    await waitFor(() => expect(result.current.blocked).toBe(false));
    expect(resolve).toHaveBeenCalledWith(TARGET, {
      currentAgentId: "a",
      signal: expect.any(AbortSignal),
    });
    expect(sessionApi.getSessionIdentity(TARGET)).toMatchObject({
      chatId: TARGET,
      sessionId: `runtime-${TARGET}`,
      userId: "target-user",
      channel: "console",
    });
  });

  it("switches to the owner and retains an explicit transition target", async () => {
    vi.spyOn(api, "resolveChat").mockResolvedValue({
      agent_id: "b",
      chat: chat(),
    });
    const { result } = mount(TARGET);

    await waitFor(() => expect(result.current.blocked).toBe(false));
    expect(useAgentStore.getState().selectedAgent).toBe("b");
    expect(result.current.agentSwitchTarget.current).toEqual({
      agentId: "b",
      referenceId: TARGET,
      chatId: TARGET,
    });
    expect(sessionApi.getSessionIdentity(TARGET).sessionId).toBe(
      `runtime-${TARGET}`,
    );
    expect(useAgentStore.getState().getLastChatId("a")).toBeUndefined();
  });

  it("keeps resolved archived identity when the sidebar list excludes it", async () => {
    vi.spyOn(api, "resolveChat").mockResolvedValue({
      agent_id: "a",
      chat: { ...chat(), archived: true },
    });
    vi.spyOn(api, "listChats").mockResolvedValue([]);
    const { result } = mount(TARGET);

    await waitFor(() => expect(result.current.blocked).toBe(false));
    await sessionApi.getSessionList();

    expect(sessionApi.getSessionIdentity(TARGET).sessionId).toBe(
      `runtime-${TARGET}`,
    );
  });

  it.each([undefined, "new"])(
    "opens draft %s without resolving or creating a persisted Chat",
    (referenceId) => {
      const resolve = vi.spyOn(api, "resolveChat");
      const create = vi.spyOn(api, "createChat");
      const { result } = mount(referenceId);

      expect(result.current.blocked).toBe(false);
      expect(resolve).not.toHaveBeenCalled();
      expect(create).not.toHaveBeenCalled();
    },
  );

  it("uses an already-known Chat in the current owner epoch", () => {
    sessionApi.registerResolvedChat(chat(), sessionApi.getActiveOwner());
    const resolve = vi.spyOn(api, "resolveChat");
    const { result } = mount(TARGET);

    expect(result.current.blocked).toBe(false);
    expect(resolve).not.toHaveBeenCalled();
  });

  it("re-resolves a known Chat after the sidebar excludes an archived Chat", async () => {
    const list = vi.spyOn(api, "listChats").mockResolvedValue([chat()]);
    const resolve = vi.spyOn(api, "resolveChat").mockResolvedValue({
      agent_id: "a",
      chat: { ...chat(), archived: true },
    });
    await sessionApi.getSessionList();
    const { result } = mount(TARGET);

    expect(result.current.blocked).toBe(false);
    expect(resolve).not.toHaveBeenCalled();
    list.mockResolvedValue([]);
    await act(async () => {
      syncSessionsGlobal(await sessionApi.getSessionList());
    });

    await waitFor(() => expect(resolve).toHaveBeenCalledOnce());
    await waitFor(() => expect(result.current.blocked).toBe(false));
    expect(result.current.error).toBeNull();
    expect(sessionApi.getSessionIdentity(TARGET).chatId).toBe(TARGET);
  });

  it("reports a deleted known Chat after the sidebar removes it", async () => {
    const list = vi.spyOn(api, "listChats").mockResolvedValue([chat()]);
    const resolve = vi
      .spyOn(api, "resolveChat")
      .mockRejectedValue(new ApiError(404, "Chat not found"));
    await sessionApi.getSessionList();
    const { result } = mount(TARGET);

    expect(result.current.blocked).toBe(false);
    list.mockResolvedValue([]);
    await act(async () => {
      syncSessionsGlobal(await sessionApi.getSessionList());
    });

    await waitFor(() => expect(result.current.error).toBeInstanceOf(ApiError));
    expect(resolve).toHaveBeenCalledOnce();
    expect(result.current.blocked).toBe(true);
    expect(result.current.error).toMatchObject({ status: 404 });
  });

  it("ignores pending resolution after the list supplies the canonical Chat", async () => {
    let finish!: (value: { agent_id: string; chat: ChatSpec }) => void;
    const resolve = vi.spyOn(api, "resolveChat").mockImplementation(
      () =>
        new Promise((done) => {
          finish = done;
        }),
    );
    vi.spyOn(api, "listChats").mockResolvedValue([chat()]);
    const { result } = mount(TARGET);
    const signal = resolve.mock.calls[0][1]?.signal;

    await act(async () => {
      syncSessionsGlobal(await sessionApi.getSessionList());
    });

    expect(result.current.blocked).toBe(false);
    expect(signal?.aborted).toBe(true);
    await act(async () => finish({ agent_id: "b", chat: chat() }));
    expect(useAgentStore.getState().selectedAgent).toBe("a");
    expect(result.current.agentSwitchTarget.current).toBeNull();
    expect(resolve).toHaveBeenCalledOnce();
  });

  it("accepts a unique runtime alias after resolving its canonical identity", async () => {
    vi.spyOn(api, "resolveChat").mockResolvedValue({
      agent_id: "a",
      chat: chat(),
    });
    const { result } = mount(`runtime-${TARGET}`);

    await waitFor(() => expect(result.current.blocked).toBe(false));
    expect(sessionApi.getSessionIdentity(`runtime-${TARGET}`).chatId).toBe(
      TARGET,
    );
  });

  it("keeps resolving when a list refresh supplies only a runtime alias", async () => {
    const alias = `runtime-${TARGET}`;
    let finish!: (value: { agent_id: string; chat: ChatSpec }) => void;
    const resolve = vi.spyOn(api, "resolveChat").mockImplementation(
      () =>
        new Promise((done) => {
          finish = done;
        }),
    );
    vi.spyOn(api, "listChats").mockResolvedValue([chat()]);
    const { result } = mount(alias);
    const signal = resolve.mock.calls[0][1]?.signal;

    sessionApi.preferredChatId = alias;
    await act(async () => {
      syncSessionsGlobal(await sessionApi.getSessionList());
    });

    expect(result.current.blocked).toBe(true);
    expect(signal?.aborted).toBe(false);
    expect(resolve).toHaveBeenCalledOnce();
    await act(async () => finish({ agent_id: "a", chat: chat() }));
    await waitFor(() => expect(result.current.blocked).toBe(false));
    expect(sessionApi.getSessionIdentity(alias).chatId).toBe(TARGET);
    expect(resolve).toHaveBeenCalledOnce();
  });

  it("resolves unknown timestamp-shaped links instead of treating them as drafts", async () => {
    const alias = "1788357954784-abc123";
    const resolve = vi.spyOn(api, "resolveChat").mockResolvedValue({
      agent_id: "a",
      chat: { ...chat(), session_id: alias },
    });
    const { result } = mount(alias);

    expect(result.current.blocked).toBe(true);
    await waitFor(() => expect(result.current.blocked).toBe(false));
    expect(resolve).toHaveBeenCalledOnce();
    expect(sessionApi.getSessionIdentity(alias).chatId).toBe(TARGET);
  });

  it("forgets resolved metadata after the Chat is removed", async () => {
    vi.spyOn(api, "deleteChat").mockResolvedValue({
      success: true,
      chat_id: TARGET,
    });
    sessionApi.registerResolvedChat(chat(), sessionApi.getActiveOwner());

    await sessionApi.removeSession({ id: TARGET });

    expect(sessionApi.getSessionIdentity(TARGET).sessionId).toBe("");
  });

  it("propagates persisted-history failures for a timestamp-shaped runtime alias", async () => {
    const alias = "1788357954784-abc123";
    sessionApi.registerResolvedChat(
      { ...chat(), session_id: alias },
      sessionApi.getActiveOwner(),
    );
    const get = vi
      .spyOn(api, "getChat")
      .mockRejectedValue(new ApiError(404, "Chat not found"));

    await expect(sessionApi.getSession(alias)).rejects.toThrow(
      "Chat not found",
    );
    expect(get).toHaveBeenCalledWith(TARGET, expect.any(Object));
  });

  it("checks global IDs before adopting a known runtime alias", async () => {
    sessionApi.registerResolvedChat(
      { ...chat("chat-a"), session_id: TARGET },
      sessionApi.getActiveOwner(),
    );
    const resolve = vi.spyOn(api, "resolveChat").mockResolvedValue({
      agent_id: "b",
      chat: chat(),
    });
    const { result } = mount(TARGET);

    expect(result.current.blocked).toBe(true);
    await waitFor(() => expect(result.current.blocked).toBe(false));
    expect(resolve).toHaveBeenCalledOnce();
    expect(useAgentStore.getState().selectedAgent).toBe("b");
  });

  it("checks global IDs before adopting a cached SDK display alias", async () => {
    const original = "11111111-1111-4111-8111-111111111111";
    vi.spyOn(api, "listChats").mockResolvedValue([
      { ...chat(original), session_id: TARGET },
    ]);
    sessionApi.preferredChatId = TARGET;
    await sessionApi.getSessionList();
    expect(sessionApi.getSessionIdentity(TARGET)).toMatchObject({
      sdkSessionId: TARGET,
      chatId: original,
    });
    const resolve = vi.spyOn(api, "resolveChat").mockResolvedValue({
      agent_id: "b",
      chat: chat(),
    });
    const { result } = mount(TARGET);

    expect(result.current.blocked).toBe(true);
    await waitFor(() => expect(result.current.blocked).toBe(false));
    expect(resolve).toHaveBeenCalledWith(TARGET, {
      currentAgentId: "a",
      signal: expect.any(AbortSignal),
    });
    expect(useAgentStore.getState().selectedAgent).toBe("b");
    expect(sessionApi.getSessionIdentity(TARGET).chatId).toBe(TARGET);
  });

  it.each([false, true])(
    "opens a same-agent archived Chat over a cached display alias (preloaded=%s)",
    async (preloaded) => {
      const original = "11111111-1111-4111-8111-111111111111";
      vi.spyOn(api, "listChats").mockResolvedValue([
        { ...chat(original), session_id: TARGET },
      ]);
      const get = vi.spyOn(api, "getChat").mockResolvedValue({
        messages: [],
        status: "idle",
      });
      sessionApi.preferredChatId = TARGET;
      await sessionApi.getSessionList();
      expect(sessionApi.getSessionIdentity(TARGET).chatId).toBe(original);
      if (preloaded) await sessionApi.preloadSession(TARGET);
      get.mockClear();
      vi.spyOn(api, "resolveChat").mockResolvedValue({
        agent_id: "a",
        chat: { ...chat(), archived: true },
      });
      const { result } = mount(TARGET);

      await waitFor(() => expect(result.current.blocked).toBe(false));
      expect(sessionApi.getSessionIdentity(TARGET).chatId).toBe(TARGET);
      await expect(sessionApi.getSession(TARGET)).resolves.toMatchObject({
        realId: TARGET,
        sessionId: `runtime-${TARGET}`,
      });
      expect(get).toHaveBeenCalledExactlyOnceWith(TARGET, expect.any(Object));

      sessionApi.preferredChatId = TARGET;
      await act(async () => {
        syncSessionsGlobal(await sessionApi.getSessionList());
      });
      expect(useSessionListStore.getState().sessions).toMatchObject([
        { id: original },
      ]);
      expect(sessionApi.getSessionIdentity(TARGET).chatId).toBe(TARGET);
    },
  );

  it.each(["none", "converted", "preloaded"] as const)(
    "loads the new Chat after a runtime alias is reassigned (cache=%s)",
    async (cache) => {
      const original = "11111111-1111-4111-8111-111111111111";
      const alias = "1788357954784-abc123";
      const list = vi
        .spyOn(api, "listChats")
        .mockResolvedValue([{ ...chat(original), session_id: alias }]);
      const get = vi.spyOn(api, "getChat").mockResolvedValue({
        messages: [],
        status: "idle",
      });
      sessionApi.preferredChatId = alias;
      await sessionApi.getSessionList();
      expect(sessionApi.getSessionIdentity(alias).chatId).toBe(original);
      if (cache === "converted") await sessionApi.getSession(alias);
      if (cache === "preloaded") await sessionApi.preloadSession(alias);
      get.mockClear();
      get.mockImplementation(async (id) => {
        if (id === original) throw new ApiError(404, "Chat not found");
        return { messages: [], status: "idle" };
      });
      vi.spyOn(api, "resolveChat").mockResolvedValue({
        agent_id: "a",
        chat: { ...chat(), session_id: alias },
      });
      const selected = vi.fn();
      sessionApi.onSessionSelected = selected;
      const { result } = mount(alias);

      await waitFor(() => expect(result.current.blocked).toBe(false));
      await expect(sessionApi.getSession(alias)).resolves.toMatchObject({
        realId: TARGET,
        sessionId: alias,
      });
      expect(sessionApi.getSessionIdentity(alias).chatId).toBe(TARGET);
      expect(get).toHaveBeenCalledExactlyOnceWith(TARGET, expect.any(Object));
      expect(selected).toHaveBeenCalledExactlyOnceWith(alias, TARGET);
      expect(useSessionListStore.getState().sessions).toMatchObject([
        { id: original, realId: original },
      ]);

      list.mockResolvedValue([{ ...chat(), session_id: alias }]);
      await act(async () => {
        syncSessionsGlobal(await sessionApi.getSessionList());
      });
      expect(useSessionListStore.getState().sessions).toMatchObject([
        { id: TARGET },
      ]);
      expect(sessionApi.getSessionIdentity(alias).chatId).toBe(TARGET);
    },
  );

  it("keeps canonical IDs ahead of a confirmed runtime alias", async () => {
    const original = "11111111-1111-4111-8111-111111111111";
    vi.spyOn(api, "listChats").mockResolvedValue([chat(original)]);
    await sessionApi.getSessionList();

    sessionApi.registerResolvedChat(
      { ...chat(), session_id: original },
      sessionApi.getActiveOwner(),
    );

    expect(sessionApi.getSessionIdentity(original).chatId).toBe(original);
    expect(sessionApi.getSessionIdentity(TARGET).chatId).toBe(TARGET);
  });

  it("rejects a late preload after a runtime alias is reassigned", async () => {
    const original = "11111111-1111-4111-8111-111111111111";
    const alias = "1788357954784-abc123";
    vi.spyOn(api, "listChats").mockResolvedValue([
      { ...chat(original), session_id: alias },
    ]);
    sessionApi.preferredChatId = alias;
    await sessionApi.getSessionList();
    const pending = deferred<ChatHistory>();
    const get = vi.spyOn(api, "getChat").mockImplementation(async (id) => {
      if (id === original) return pending.promise;
      return { messages: [], status: "idle" };
    });
    const stale = Promise.allSettled([sessionApi.preloadSession(alias)]);
    vi.spyOn(api, "resolveChat").mockResolvedValue({
      agent_id: "a",
      chat: { ...chat(), session_id: alias },
    });
    const { result } = mount(alias);
    await waitFor(() => expect(result.current.blocked).toBe(false));
    const fresh = sessionApi.getSession(alias);
    const requestedTarget = get.mock.calls.some(([id]) => id === TARGET);
    pending.resolve({ messages: [], status: "idle" });

    expect(requestedTarget).toBe(true);
    await expect(fresh).resolves.toMatchObject({ realId: TARGET });
    expect(await stale).toMatchObject([
      { status: "rejected", reason: { name: "AbortError" } },
    ]);
    await expect(sessionApi.getSession(alias)).resolves.toMatchObject({
      realId: TARGET,
      sessionId: alias,
    });
  });

  it("rejects a late preload for an alias claimed by a canonical Chat", async () => {
    const original = "11111111-1111-4111-8111-111111111111";
    vi.spyOn(api, "listChats").mockResolvedValue([
      { ...chat(original), session_id: TARGET },
    ]);
    sessionApi.preferredChatId = TARGET;
    await sessionApi.getSessionList();
    const pending = deferred<ChatHistory>();
    const get = vi.spyOn(api, "getChat").mockImplementation(async (id) => {
      if (id === original) return pending.promise;
      return { messages: [], status: "idle" };
    });
    const stale = Promise.allSettled([sessionApi.preloadSession(TARGET)]);
    vi.spyOn(api, "resolveChat").mockResolvedValue({
      agent_id: "a",
      chat: { ...chat(), archived: true },
    });
    const { result } = mount(TARGET);
    await waitFor(() => expect(result.current.blocked).toBe(false));
    const fresh = sessionApi.getSession(TARGET);
    pending.resolve({ messages: [], status: "idle" });

    await expect(fresh).resolves.toMatchObject({ realId: TARGET });
    expect(await stale).toMatchObject([
      { status: "rejected", reason: { name: "AbortError" } },
    ]);
    expect(get).toHaveBeenCalledWith(TARGET, expect.any(Object));
    await expect(sessionApi.getSession(TARGET)).resolves.toMatchObject({
      realId: TARGET,
    });
  });

  it.each([404, 409])(
    "blocks every render of a repeated alias while its new resolution awaits %s",
    async (status) => {
      const alias = `runtime-${TARGET}`;
      const pending = deferred<{ agent_id: string; chat: ChatSpec }>();
      const resolve = vi
        .spyOn(api, "resolveChat")
        .mockResolvedValueOnce({ agent_id: "a", chat: chat() })
        .mockReturnValueOnce(pending.promise);
      const renders: boolean[] = [];
      const { result, rerender } = renderHook(
        ({ referenceId }) => {
          const { selectedAgent } = useAgentStore();
          const resolution = useChatRouteResolution(referenceId, selectedAgent);
          renders.push(resolution.blocked);
          return resolution;
        },
        { initialProps: { referenceId: alias } },
      );
      await waitFor(() => expect(result.current.blocked).toBe(false));
      rerender({ referenceId: "new" });
      renders.length = 0;
      rerender({ referenceId: alias });

      expect(resolve).toHaveBeenCalledTimes(2);
      expect(renders.length).toBeGreaterThan(0);
      expect(renders.every(Boolean)).toBe(true);
      await act(async () => {
        pending.reject(new ApiError(status, "Unavailable Chat reference"));
      });
      expect(result.current.blocked).toBe(true);
      expect(result.current.error).toMatchObject({ status });
    },
  );

  it.each([
    [TARGET, "archived"],
    [TARGET, "deleted"],
    [`runtime-${TARGET}`, "archived"],
    [`runtime-${TARGET}`, "deleted"],
  ] as const)(
    "revalidates a cold-resolved link %s when its Chat is %s",
    async (referenceId, outcome) => {
      const pending = deferred<{ agent_id: string; chat: ChatSpec }>();
      const resolve = vi
        .spyOn(api, "resolveChat")
        .mockResolvedValueOnce({ agent_id: "a", chat: chat() })
        .mockReturnValueOnce(pending.promise);
      const list = vi.spyOn(api, "listChats").mockResolvedValue([chat()]);
      const { result } = mount(referenceId);
      await waitFor(() => expect(result.current.blocked).toBe(false));
      await act(async () => {
        syncSessionsGlobal(await sessionApi.getSessionList());
      });
      expect(useSessionListStore.getState().sessions).toHaveLength(1);
      list.mockResolvedValue([]);
      await act(async () => {
        syncSessionsGlobal(await sessionApi.getSessionList());
      });

      expect(resolve).toHaveBeenCalledTimes(2);
      expect(result.current.blocked).toBe(true);
      await act(async () => {
        if (outcome === "archived") {
          pending.resolve({
            agent_id: "a",
            chat: { ...chat(), archived: true },
          });
        } else {
          pending.reject(new ApiError(404, "Chat not found"));
        }
      });
      expect(result.current.blocked).toBe(outcome === "deleted");
      if (outcome === "deleted") {
        expect(result.current.error).toMatchObject({ status: 404 });
      } else {
        expect(result.current.error).toBeNull();
        expect(sessionApi.getSessionIdentity(TARGET).chatId).toBe(TARGET);
      }
      await act(async () => {
        syncSessionsGlobal(await sessionApi.getSessionList());
      });
      expect(resolve).toHaveBeenCalledTimes(2);
    },
  );

  it("keeps not-found links blocked and can retry the same reference", async () => {
    const resolve = vi
      .spyOn(api, "resolveChat")
      .mockRejectedValueOnce(new ApiError(404, "Chat not found"))
      .mockResolvedValueOnce({ agent_id: "a", chat: chat() });
    const { result } = mount(TARGET);

    await waitFor(() => expect(result.current.error).toBeInstanceOf(ApiError));
    expect(result.current.blocked).toBe(true);
    expect(useAgentStore.getState().getLastChatId("a")).toBeUndefined();
    act(() => result.current.retry());
    await waitFor(() => expect(result.current.blocked).toBe(false));
    expect(resolve).toHaveBeenCalledTimes(2);
    expect(result.current.error).toBeNull();
  });

  it("ignores a late resolution after navigating to another link", async () => {
    let finish!: (value: { agent_id: string; chat: ChatSpec }) => void;
    const resolve = vi
      .spyOn(api, "resolveChat")
      .mockImplementationOnce(
        () =>
          new Promise((done) => {
            finish = done;
          }),
      )
      .mockResolvedValueOnce({ agent_id: "a", chat: chat("next-chat") });
    const { result, rerender } = mount(TARGET);
    const firstSignal = resolve.mock.calls[0][1]?.signal;
    rerender({ referenceId: "next-chat" });
    await waitFor(() => expect(result.current.blocked).toBe(false));
    await act(async () => finish({ agent_id: "b", chat: chat() }));

    expect(firstSignal?.aborted).toBe(true);
    expect(useAgentStore.getState().selectedAgent).toBe("a");
    expect(sessionApi.getSessionIdentity(TARGET).sessionId).toBe("");
    expect(sessionApi.getSessionIdentity("next-chat").sessionId).toBe(
      "runtime-next-chat",
    );
  });

  it("rejects a late result from an earlier A → B → A owner epoch", async () => {
    let finish!: (value: { agent_id: string; chat: ChatSpec }) => void;
    vi.spyOn(api, "resolveChat").mockImplementation(
      () =>
        new Promise((done) => {
          finish = done;
        }),
    );
    const { result } = mount(TARGET);
    sessionApi.setActiveAgent("b");
    sessionApi.setActiveAgent("a");
    await act(async () => finish({ agent_id: "b", chat: chat() }));

    expect(useAgentStore.getState().selectedAgent).toBe("a");
    expect(result.current.blocked).toBe(true);
    expect(sessionApi.getSessionIdentity(TARGET).sessionId).toBe("");
  });
});
