/**
 * Installed-SDK protocol integration, NOT browser/backend/model E2E.
 *
 * No @agentscope-ai/chat module, context, hook, controller or session adapter
 * is mocked. HTTP-client fixtures supply chat records; a real ReadableStream
 * drives the SDK SSE reader. The small router host reproduces CoPaw's controlled
 * currentSessionId and SDK-confirmed onSessionCreated navigation. It does not
 * mount ChatPage's queue drain/ownership effects, so pending host queue assertions
 * establish isolation, not background-drain or cross-tab acceptance.
 *
 * The unobserved loading test characterizes pinned beta
 * 1.2.0-beta.1789540479556. If an SDK upgrade clears idle loading itself,
 * its expected-true assertion fails: review removal of the host workaround.
 * Observed-path regression tests independently require loading=false.
 * Run: npm run test:run -- src/pages/Chat/sdkSessionLifecycle.integration.test.tsx
 */
import { useLayoutEffect, useMemo } from "react";
import { act, cleanup, render, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation, useNavigate } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  useChatAnywhereInput,
  useChatAnywhereSessionsState,
} from "@agentscope-ai/chat";
import { useChatAnywhereMessages } from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/Context/ChatAnywhereMessagesContext";
import ComposedProvider from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/ChatAnywhere/ComposedProvider";
import useChatController from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/Chat/hooks/useChatController";
import { useChatAnywhereSessionLoader } from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/Context/ChatAnywhereSessionsContext";
import type { IAgentScopeRuntimeWebUIOptions } from "@agentscope-ai/chat";
import api, { type ChatSpec } from "../../api";
import { useAgentStore } from "../../stores/agentStore";
import { useMessageQueueStore } from "../../stores/messageQueueStore";
import { useCreateNewSession } from "./hooks/useCreateNewSession";
import sessionApi from "./sessionApi";
import { createSdkSessionAdapter } from "./sdkSessionAdapter";
import { cancelSdkChatRequest } from "./sdkCancellation";
import { useChatAnywhereCommandDispatcher } from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/Context/useChatAnywhereEventEmitter";

const A = "11111111-1111-4111-8111-111111111111";
const B = "22222222-2222-4222-8222-222222222222";
const AGENT = "default";

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function record(id: string, name = id): ChatSpec {
  return {
    id,
    name,
    session_id: `runtime-${id}`,
    user_id: "default",
    channel: "console",
    created_at: null,
    updated_at: null,
    status: "idle",
  };
}

type TransportData = Parameters<
  NonNullable<NonNullable<IAgentScopeRuntimeWebUIOptions["api"]>["fetch"]>
>[0];

function createFixture() {
  const records = [record(A)];
  const trace: string[] = [];
  const streams: Array<{
    data: TransportData;
    close: () => void;
    emit: (event: Record<string, unknown>) => void;
  }> = [];
  const stop = vi.fn(async (_id: string) => {});
  const create = vi
    .spyOn(api, "createChat")
    .mockImplementation(async (draft) => {
      const chat = {
        ...record(records.length === 1 ? B : `unexpected-${records.length}`),
        ...draft,
      };
      records.push(chat);
      trace.push(`POST:${chat.id}`);
      return chat;
    });
  vi.spyOn(api, "listChats").mockImplementation(async () => [...records]);
  const history = vi.spyOn(api, "getChat").mockImplementation(async (id) => {
    trace.push(`GET-idle:${id}`);
    return { status: "idle", messages: [] };
  });
  const transport = vi.fn(async (data: TransportData) => {
    trace.push(`SSE:${data.session_id}`);
    let close = () => {};
    let emit = (_event: Record<string, unknown>) => {};
    let closed = false;
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        emit = (event) =>
          controller.enqueue(
            new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`),
          );
        close = () => {
          if (closed) return;
          closed = true;
          controller.close();
        };
        controller.enqueue(
          new TextEncoder().encode(
            `data: ${JSON.stringify({
              object: "response",
              id: `run-${data.session_id}`,
              status: "in_progress",
              created_at: 1,
              output: [],
            })}\n\n`,
          ),
        );
        data.signal?.addEventListener("abort", close, { once: true });
      },
      cancel() {
        closed = true;
        data.signal?.removeEventListener("abort", close);
      },
    });
    streams.push({ data, close, emit });
    return new Response(body, {
      headers: { "Content-Type": "text/event-stream" },
    });
  });
  return { records, trace, create, history, transport, streams, stop };
}

type Fixture = ReturnType<typeof createFixture>;
type Probe = {
  dispatch: ReturnType<typeof useChatAnywhereCommandDispatcher>;
  path: string;
  newChat: ReturnType<typeof useCreateNewSession>;
  navigate: ReturnType<typeof useNavigate>;
  sessions: ReturnType<typeof useChatAnywhereSessionsState>;
  input: ReturnType<typeof useInputSnapshot>;
  messages: ReturnType<typeof useChatAnywhereMessages>;
  controller: ReturnType<typeof useChatController>;
};

function useInputSnapshot() {
  return useChatAnywhereInput((state) => state);
}

function mountHost(
  fixture: Fixture,
  creationGate?: ReturnType<typeof deferred>,
  observeIdle = false,
) {
  let probe!: Probe;
  const loaded: Array<{ id: string; generating: boolean }> = [];
  // These are forwarding methods, not replacements for SDK/CoPaw behavior.
  const sessionMethods = {
    getSessionList: () => sessionApi.getSessionList(),
    getSession: async (id: string) => {
      const session = await sessionApi.getSession(id);
      loaded.push({ id, generating: !!session?.generating });
      return session;
    },
    createSession: async (
      draft: Parameters<typeof sessionApi.createSession>[0],
    ) => {
      const result = await sessionApi.createSession(draft);
      fixture.trace.push("host-create-resolved");
      // Hold the adapter result: no host navigation is allowed until the SDK
      // accepts creation. Never modify SDK internals to force a race.
      if (creationGate) await creationGate.promise;
      fixture.trace.push("adapter-create-return");
      return result;
    },
    updateSession: (draft: Parameters<typeof sessionApi.updateSession>[0]) =>
      sessionApi.updateSession(draft),
    removeSession: (draft: Parameters<typeof sessionApi.removeSession>[0]) =>
      sessionApi.removeSession(draft),
  };
  const observerCalls: Array<{
    id: string;
    generating: boolean;
    ready: boolean;
  }> = [];
  const adapter = createSdkSessionAdapter(
    sessionMethods,
    observeIdle
      ? (id, session) => {
          observerCalls.push({
            id,
            generating: !!session?.generating,
            ready: adapter.isReady(id),
          });
          if (session && !session.generating)
            probe?.input.setSessionLoading?.(id, false);
        }
      : undefined,
  );
  const readySnapshots: Array<{
    id: string;
    loading: boolean | string;
    sessionLoading: boolean | string | undefined;
  }> = [];
  const unsubscribe = adapter.subscribe(() => {
    const id = probe?.sessions.currentSessionId;
    if (id && adapter.isReady(id))
      readySnapshots.push({
        id,
        loading: probe.input.getLoading(),
        sessionLoading: probe.input.getSessionLoading?.(id),
      });
  });

  function ProbeView() {
    const controller = useChatController();
    const dispatch = useChatAnywhereCommandDispatcher();
    useChatAnywhereSessionLoader();
    const newChat = useCreateNewSession();
    const sessions = useChatAnywhereSessionsState();
    const input = useInputSnapshot();
    const messages = useChatAnywhereMessages();
    const navigate = useNavigate();
    const { pathname: path } = useLocation();
    useLayoutEffect(() => {
      probe = {
        dispatch,
        path,
        newChat,
        navigate,
        sessions,
        input,
        messages,
        controller,
      };
    });
    return null;
  }

  function RouterHost() {
    const { pathname } = useLocation();
    const navigate = useNavigate();
    const currentSessionId = pathname.split("/")[2] || undefined;
    useLayoutEffect(() => {
      sessionApi.invalidateSessionCreation();
      return () => sessionApi.invalidateSessionCreation();
    }, [currentSessionId]);
    useLayoutEffect(() => {
      sessionApi.onSessionCreated = (id) => {
        fixture.trace.push(`onSessionCreated:${id}`);
        sessionApi.lastActiveChatId = id;
        useAgentStore.getState().setLastChatId(AGENT, id);
        navigate(`/chat/${id}`, { replace: true });
      };
      return () => {
        sessionApi.onSessionCreated = null;
      };
    }, [navigate]);
    const options = useMemo<IAgentScopeRuntimeWebUIOptions>(
      () => ({
        session: {
          multiple: true,
          currentSessionId,
          api: adapter.api,
          onCurrentSessionChange: (id) => sessionApi.activateCreatedSession(id),
        },
        sender: { queue: false },
        api: {
          fetch: fixture.transport,
          cancel: (data) =>
            cancelSdkChatRequest(data, {
              resolveBackendSessionId: (id) =>
                sessionApi.getRealIdForSession(id),
              stopChat: fixture.stop,
            }),
          reconnect: (data) => fixture.transport({ ...data, input: [] }),
        },
      }),
      [currentSessionId],
    );
    return (
      <ComposedProvider options={options} cards={{}}>
        <ProbeView />
      </ComposedProvider>
    );
  }

  render(
    <MemoryRouter initialEntries={[`/chat/${A}`]}>
      <RouterHost />
    </MemoryRouter>,
  );
  return {
    current: () => probe,
    loaded,
    adapter,
    observerCalls,
    readySnapshots,
    unsubscribe,
  };
}

let fixture: Fixture;
let pendingSubmissions: Promise<unknown>[];
let gates: Array<ReturnType<typeof deferred>>;

beforeEach(() => {
  sessionApi.resetForTests();
  useAgentStore.setState({ selectedAgent: AGENT, lastChatIdByAgent: {} });
  useMessageQueueStore.setState({ queues: {}, runStates: {} });
  localStorage.clear();
  pendingSubmissions = [];
  gates = [];
  fixture = createFixture();
  // Unexpected network requests must fail, never reach a live backend.
  vi.stubGlobal(
    "fetch",
    vi.fn(() => {
      throw new Error("Unexpected live fetch in SDK protocol test");
    }),
  );
});

afterEach(async () => {
  cleanup();
  gates.forEach((gate) => gate.resolve());
  fixture.streams.forEach((stream) => stream.close());
  await Promise.allSettled(pendingSubmissions);
  sessionApi.resetForTests();
  useMessageQueueStore.setState({ queues: {}, runStates: {} });
  useAgentStore.setState({ lastChatIdByAgent: {} });
  localStorage.clear();
  sessionStorage.clear();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

async function startA(host: ReturnType<typeof mountHost>) {
  await waitFor(() =>
    expect(host.loaded).toContainEqual({ id: A, generating: false }),
  );
  act(() => {
    pendingSubmissions.push(
      Promise.resolve(
        host.current().controller.handleSubmit({
          query: "A still streaming",
          fileList: [],
        }),
      ),
    );
  });
  await waitFor(() => expect(fixture.transport).toHaveBeenCalledTimes(1));
  expect(host.current().sessions.currentSessionId).toBe(A);
  expect(host.current().input.getLoading()).toBe(true);
  expect(fixture.streams[0].data.signal?.aborted).toBe(false);
  useMessageQueueStore.getState().enqueue(A, {
    text: "A pending host message",
    agentId: AGENT,
    backendSessionId: `runtime-${A}`,
    userId: "default",
    channel: "console",
  });
  expect(host.current().controller.inputQueueEnabled).toBe(false);
  expect(host.current().controller.inputQueue).toEqual([]);
}

describe("installed SDK session lifecycle with CoPaw's blank-new hook", () => {
  it("keeps the presented history while switching and commits an empty target only after load", async () => {
    const host = mountHost(fixture);
    await waitFor(() =>
      expect(host.loaded).toContainEqual({ id: A, generating: false }),
    );
    act(() =>
      host
        .current()
        .messages.setSessionMessages(A, [{ id: "visible-a", role: "user" }]),
    );
    const gate = deferred();
    gates.push(gate);
    fixture.history.mockImplementation(async () => {
      await gate.promise;
      return { status: "idle", messages: [] };
    });
    await act(async () => {
      host.current().navigate(`/chat/${B}`);
    });
    await waitFor(() =>
      expect(fixture.history).toHaveBeenCalledWith(B, expect.any(Object)),
    );
    expect(
      host
        .current()
        .messages.getMessages()
        .map((message) => message.id),
    ).toEqual(["visible-a"]);
    expect(host.adapter.isReady(B)).toBe(false);
    await act(async () => {
      gate.resolve();
    });
    await waitFor(() =>
      expect(host.current().messages.getMessages()).toEqual([]),
    );
    expect(host.adapter.isReady(B)).toBe(true);
  });

  it("ignores a late target after a rapid switch back", async () => {
    const host = mountHost(fixture);
    await waitFor(() =>
      expect(host.loaded).toContainEqual({ id: A, generating: false }),
    );
    act(() =>
      host
        .current()
        .messages.setSessionMessages(A, [{ id: "visible-a", role: "user" }]),
    );
    const gate = deferred();
    gates.push(gate);
    fixture.history.mockImplementation(async (id) => {
      if (id === B) await gate.promise;
      return { status: "idle", messages: [] };
    });
    await act(async () => {
      host.current().navigate(`/chat/${B}`);
    });
    await waitFor(() =>
      expect(fixture.history).toHaveBeenCalledWith(B, expect.any(Object)),
    );
    await act(async () => {
      host.current().navigate(`/chat/${A}`);
    });
    await act(async () => {
      gate.resolve();
    });
    expect(host.current().sessions.currentSessionId).toBe(A);
    expect(
      host
        .current()
        .messages.getMessages()
        .map((message) => message.id),
    ).toEqual(["visible-a"]);
  });

  it("A SSE + pending host queue → repeated blank new allocates no session and clears real context", async () => {
    const host = mountHost(fixture);
    await startA(host);
    const queue = useMessageQueueStore.getState().queues[A];
    sessionApi.lastActiveChatId = A;
    sessionApi.preferredChatId = A;
    useAgentStore.getState().setLastChatId(AGENT, A);
    for (let count = 0; count < 3; count++) {
      await act(async () => {
        await host.current().newChat();
      });
      expect(host.current().path).toBe("/chat");
      expect(host.current().sessions.currentSessionId).toBeUndefined();
      expect(host.current().messages.getMessages()).toEqual([]);
      expect(host.current().input.getLoading()).toBe(false);
    }
    await act(async () => {
      await Promise.all([
        host.current().newChat(),
        host.current().newChat(),
        host.current().newChat(),
      ]);
    });
    expect(host.current().path).toBe("/chat");
    expect(host.current().sessions.currentSessionId).toBeUndefined();
    expect(fixture.create).not.toHaveBeenCalled();
    expect(fixture.streams[0].data.signal?.aborted).toBe(true);
    expect(sessionApi.lastActiveChatId).toBeNull();
    expect(sessionApi.preferredChatId).toBeNull();
    expect(useAgentStore.getState().getLastChatId(AGENT)).toBeUndefined();
    expect(useMessageQueueStore.getState().queues[A]).toEqual(queue);
  });

  it.each([false, true])(
    "A → blank → first send activates only after the adapter returns (delayed=%s)",
    async (commitBeforeReturn) => {
      const gate = commitBeforeReturn ? deferred() : undefined;
      if (gate) gates.push(gate);
      const host = mountHost(fixture, gate);
      await startA(host);
      const queue = useMessageQueueStore.getState().queues[A];
      await act(async () => {
        await host.current().newChat();
      });
      expect(fixture.create).not.toHaveBeenCalled();
      act(() => {
        pendingSubmissions.push(
          Promise.resolve(
            host.current().controller.handleSubmit({
              query: "First B message",
              fileList: [],
            }),
          ),
        );
      });
      await waitFor(() =>
        expect(fixture.trace).toContain("host-create-resolved"),
      );
      if (gate) {
        expect(host.current().path).toBe("/chat");
        expect(fixture.trace).not.toContain(`onSessionCreated:${B}`);
        expect(fixture.trace).not.toContain("adapter-create-return");
        expect(fixture.transport).toHaveBeenCalledTimes(1);
        await act(async () => {
          gate.resolve();
        });
      }
      await waitFor(() => expect(fixture.transport).toHaveBeenCalledTimes(2));
      expect(fixture.trace.indexOf(`onSessionCreated:${B}`)).toBeGreaterThan(
        fixture.trace.indexOf("adapter-create-return"),
      );
      expect(fixture.create).toHaveBeenCalledTimes(1);
      expect(fixture.records.map((chat) => chat.id)).toEqual([A, B]);
      expect(host.current().path).toBe(`/chat/${B}`);
      expect(host.current().sessions.currentSessionId).toBe(B);
      expect(
        fixture.streams[1].data.chatSessionId ??
          fixture.streams[1].data.session_id,
      ).toBe(B);
      expect(JSON.stringify(fixture.streams[1].data.input)).toContain(
        "First B message",
      );
      expect(
        JSON.stringify(host.current().messages.getSessionMessages(B)),
      ).toContain("First B message");
      expect(useMessageQueueStore.getState().queues[A]).toEqual(queue);
      expect(useMessageQueueStore.getState().queues[B] ?? []).toEqual([]);
    },
  );

  it("[pinned beta characterization: observer disabled] A → blank → A idle history retains stale loading", async () => {
    const host = mountHost(fixture);
    await startA(host);
    const queue = useMessageQueueStore.getState().queues[A];
    await act(async () => {
      await host.current().newChat();
    });
    expect(host.current().input.getLoading()).toBe(false);
    await act(async () => {
      host.current().navigate(`/chat/${A}`);
    });
    await waitFor(() =>
      expect(host.loaded.filter((load) => load.id === A)).toHaveLength(2),
    );
    expect(host.loaded[host.loaded.length - 1]).toEqual({
      id: A,
      generating: false,
    });
    expect(fixture.streams[0].data.signal?.aborted).toBe(true);
    expect(fixture.transport).toHaveBeenCalledTimes(1);
    expect(useMessageQueueStore.getState().queues[A]).toEqual(queue);
    expect(host.current().controller.inputQueueEnabled).toBe(false);
    await waitFor(() => {
      expect(
        host.current().input.getLoading(),
        "Pinned beta keeps stale loading after idle history; if fixed upstream, review the host workaround",
      ).toBe(true);
      expect(host.current().input.loading).toBe(true);
    });
  });

  it("adapter idle observer clears the real SDK session loading before publishing readiness", async () => {
    const host = mountHost(fixture, undefined, true);
    await startA(host);
    await act(async () => {
      await host.current().newChat();
    });
    host.readySnapshots.length = 0;
    await act(async () => {
      host.current().navigate(`/chat/${A}`);
    });
    await waitFor(() =>
      expect(host.loaded.filter((load) => load.id === A)).toHaveLength(2),
    );
    expect(host.observerCalls[host.observerCalls.length - 1]).toEqual({
      id: A,
      generating: false,
      ready: false,
    });
    expect(host.adapter.isReady(A)).toBe(true);
    expect(host.readySnapshots.length).toBeGreaterThan(0);
    expect(
      host.readySnapshots.every(
        (snapshot) => snapshot.sessionLoading === false,
      ),
    ).toBe(true);
    // The SDK's active getLoading() is backed by ahooks useGetState: it can
    // retain the pre-commit value here. The per-session cache is synchronous;
    // React must subsequently publish false to the public visible state.
    await waitFor(() => expect(host.current().input.loading).toBe(false));
    expect(host.current().input.getSessionLoading?.(A)).toBe(false);
    expect(useMessageQueueStore.getState().queues[A][0].status).toBe("pending");
    host.unsubscribe();
  });

  it("adapter observer preserves loading for running history and the SDK reconnects A", async () => {
    const host = mountHost(fixture, undefined, true);
    await startA(host);
    await act(async () => {
      await host.current().newChat();
    });
    fixture.history.mockResolvedValue({ status: "running", messages: [] });
    // Real host refresh invalidates the old idle cache before restoring A.
    await act(async () => {
      await sessionApi.refreshSession(A);
    });
    await act(async () => {
      host.current().navigate(`/chat/${A}`);
    });
    await waitFor(() =>
      expect(host.loaded[host.loaded.length - 1]).toEqual({
        id: A,
        generating: true,
      }),
    );
    expect(host.observerCalls[host.observerCalls.length - 1]).toEqual({
      id: A,
      generating: true,
      ready: false,
    });
    await waitFor(() => expect(fixture.transport).toHaveBeenCalledTimes(2));
    expect(host.current().input.getLoading()).toBe(true);
    expect(host.current().input.getSessionLoading?.(A)).toBe(true);
    expect(fixture.streams[1].data.signal?.aborted).toBe(false);
    host.unsubscribe();
  });

  it("observing idle A clears only A while B's real SDK SSE remains loading", async () => {
    const host = mountHost(fixture, undefined, true);
    await startA(host);
    await act(async () => {
      await host.current().newChat();
    });
    act(() => {
      pendingSubmissions.push(
        Promise.resolve(
          host
            .current()
            .controller.handleSubmit({ query: "B streaming", fileList: [] }),
        ),
      );
    });
    await waitFor(() => expect(fixture.transport).toHaveBeenCalledTimes(2));
    expect(host.current().sessions.currentSessionId).toBe(B);
    await act(async () => {
      await host.adapter.api.getSession(A);
    });
    expect(host.current().input.getSessionLoading?.(A)).toBe(false);
    expect(host.current().input.getSessionLoading?.(B)).toBe(true);
    expect(host.current().input.getLoading()).toBe(true);
    expect(fixture.streams[1].data.signal?.aborted).toBe(false);
    host.unsubscribe();
  });

  it("two first-send controller submissions before create returns must not persist a duplicate empty chat", async () => {
    const gate = deferred();
    gates.push(gate);
    const host = mountHost(fixture, gate, true);
    await startA(host);
    await act(async () => {
      await host.current().newChat();
    });
    act(() => {
      for (let click = 0; click < 2; click++) {
        const submission = Promise.resolve(
          host.current().controller.handleSubmit({
            query: "First B message",
            fileList: [],
          }),
        );
        // Record rejection without creating an unhandled rejection. SDK may
        // invalidate the older concurrent submit; that must not leave its Chat.
        pendingSubmissions.push(
          submission.catch((error: unknown) => {
            fixture.trace.push(`submit-rejected:${String(error)}`);
          }),
        );
      }
    });
    await waitFor(() =>
      expect(fixture.trace).toContain("host-create-resolved"),
    );
    await act(async () => {
      gate.resolve();
    });
    await waitFor(() => expect(fixture.transport).toHaveBeenCalledTimes(2));
    expect(fixture.create, JSON.stringify(fixture.trace)).toHaveBeenCalledTimes(
      1,
    );
    expect(fixture.records.map((chat) => chat.id)).toEqual([A, B]);
    expect(
      fixture.trace.filter((event) => event === `onSessionCreated:${B}`),
    ).toHaveLength(1);
    expect(
      JSON.stringify(host.current().messages.getSessionMessages(B)),
    ).toContain("First B message");
    expect(useMessageQueueStore.getState().queues[A][0].status).toBe("pending");
  });
});

describe("late first-send creation with the published SDK", () => {
  it.each([false, true])(
    "does not steal selection after switching away (return to blank=%s)",
    async (backToBlank) => {
      const gate = deferred();
      gates.push(gate);
      fixture.create.mockImplementationOnce(async (draft) => {
        await gate.promise;
        const chat = { ...record(B), ...draft };
        fixture.records.push(chat);
        return chat;
      });
      const host = mountHost(fixture);
      await waitFor(() => expect(host.loaded.length).toBeGreaterThan(0));
      await act(async () => {
        await host.current().newChat();
      });
      let rejection: unknown;
      act(() => {
        pendingSubmissions.push(
          Promise.resolve(
            host
              .current()
              .controller.handleSubmit({ query: "late first", fileList: [] }),
          ).catch((error) => {
            rejection = error;
          }),
        );
      });
      await waitFor(() => expect(fixture.create).toHaveBeenCalledOnce());
      await act(async () => {
        host.current().navigate(`/chat/${A}`);
      });
      if (backToBlank)
        await act(async () => {
          await host.current().newChat();
        });
      await act(async () => {
        gate.resolve();
      });
      await waitFor(() =>
        expect(rejection).toMatchObject({ name: "AbortError" }),
      );
      expect(host.current().path).toBe(backToBlank ? "/chat" : `/chat/${A}`);
      expect(host.current().sessions.currentSessionId).toBe(
        backToBlank ? undefined : A,
      );
      expect(fixture.trace).not.toContain(`onSessionCreated:${B}`);
      expect(fixture.transport).not.toHaveBeenCalled();
    },
  );
});

describe("published SDK cancellation with CoPaw adapter", () => {
  it.each(["ui", "public"] as const)(
    "%s cancellation consumes a late SSE terminal after Stop HTTP success",
    async (mode) => {
      const host = mountHost(fixture);
      await waitFor(() =>
        expect(host.loaded).toContainEqual({ id: A, generating: false }),
      );
      const handle = await act(async () =>
        host.current().dispatch("handleExecute", {
          data: { query: "cancel me", fileList: [] },
          options: { sessionId: A },
        }),
      );
      await act(async () => {
        await handle.accepted;
      });
      let settled = false;
      const completion = handle.completion.then((result) => {
        settled = true;
        return result;
      });
      let cancellation: ReturnType<typeof handle.cancel> | undefined;
      act(() => {
        if (mode === "ui") host.current().controller.handleCancel();
        else cancellation = handle.cancel();
      });
      await waitFor(() => expect(fixture.stop).toHaveBeenCalledWith(A));
      expect(fixture.streams[0].data.signal?.aborted).toBe(false);
      expect(settled).toBe(false);
      await act(async () => {
        fixture.streams[0].emit({
          object: "response",
          id: "server-cancel-terminal",
          status: "canceled",
          created_at: 1,
          output: [],
        });
        expect((await completion).status).toBe("canceled");
        if (cancellation)
          expect((await cancellation).locallyCanceled).toBe(false);
      });
      expect(
        JSON.stringify(host.current().messages.getSessionMessages(A)),
      ).toContain("server-cancel-terminal");
      expect(host.current().input.getSessionLoading?.(A)).toBe(false);
    },
  );
});
