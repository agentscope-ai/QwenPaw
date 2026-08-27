/**
 * Regression tests for cross-agent ownership in the shared session-list CRUD
 * handlers: a delete started under agent A must not mutate the view after the
 * user switches to agent B, while same-agent CRUD keeps working.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import React from "react";
import { App } from "antd";
import { MemoryRouter } from "react-router-dom";
import type { ChatSpec } from "../../../../api";
import api from "../../../../api";
import { chatApi } from "../../../../api/modules/chat";
import sessionApi from "../../sessionApi";
import { useAgentStore } from "../../../../stores/agentStore";
import { useSessionListStore } from "../../../../stores/sessionListStore";
import {
  useSessionListData,
  type ExtendedChatSession,
} from "./useSessionListData";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const A_CHAT = "33333333-aaaa-4aaa-8aaa-333333333333";

const makeSession = (id: string): ExtendedChatSession =>
  ({ id, name: id, messages: [] }) as unknown as ExtendedChatSession;

function wrapper({ children }: { children: ReactNode }) {
  return React.createElement(
    App,
    null,
    React.createElement(MemoryRouter, null, children),
  );
}

function renderListData(sessions: ExtendedChatSession[]) {
  const setSessions = vi.fn();
  const hook = renderHook(
    () =>
      useSessionListData(sessions, setSessions, {
        active: false,
        currentSessionId: A_CHAT,
        onSessionClick: vi.fn(),
      }),
    { wrapper },
  );
  return { hook, setSessions };
}

beforeEach(() => {
  sessionApi.resetForTests();
  useAgentStore.setState({ selectedAgent: "agent-a", lastChatIdByAgent: {} });
  useSessionListStore.setState({
    sessions: [],
    lastUpdated: 0,
    _setLibrarySessions: null,
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  sessionApi.resetForTests();
});

describe("useSessionListData cross-agent ownership", () => {
  it("a delete finishing after an agent switch does not mutate the new view", async () => {
    sessionApi.setActiveAgent("agent-a");
    const onSessionRemoved = vi.fn();
    sessionApi.onSessionRemoved = onSessionRemoved;
    const newChatListener = vi.fn();
    window.addEventListener("qwenpaw:sidebar-new-chat", newChatListener);

    const dDelete = deferred<Awaited<ReturnType<typeof chatApi.deleteChat>>>();
    vi.spyOn(chatApi, "deleteChat").mockReturnValue(dDelete.promise);
    const listSpy = vi.spyOn(api, "listChats").mockResolvedValue([]);

    const { hook, setSessions } = renderListData([makeSession(A_CHAT)]);

    act(() => {
      hook.result.current.handleDelete(A_CHAT);
    });

    // The user switches to agent B while the backend delete is in flight.
    sessionApi.setActiveAgent("agent-b");
    useSessionListStore.setState({ sessions: [makeSession("chat-b")] });

    dDelete.resolve({} as Awaited<ReturnType<typeof chatApi.deleteChat>>);
    await act(async () => {
      await new Promise((res) => setTimeout(res, 0));
    });

    // The late completion must not touch B's view or callbacks.
    expect(onSessionRemoved).not.toHaveBeenCalled();
    expect(setSessions).not.toHaveBeenCalled();
    expect(useSessionListStore.getState().sessions.map((s) => s.id)).toEqual([
      "chat-b",
    ]);
    expect(newChatListener).not.toHaveBeenCalled();
    expect(listSpy).not.toHaveBeenCalled();

    window.removeEventListener("qwenpaw:sidebar-new-chat", newChatListener);
  });

  it("a same-agent delete still refreshes the list and fires callbacks", async () => {
    sessionApi.setActiveAgent("agent-a");
    const onSessionRemoved = vi.fn();
    sessionApi.onSessionRemoved = onSessionRemoved;

    vi.spyOn(chatApi, "deleteChat").mockResolvedValue(
      {} as Awaited<ReturnType<typeof chatApi.deleteChat>>,
    );
    vi.spyOn(api, "listChats").mockResolvedValue([] as ChatSpec[]);

    const { hook, setSessions } = renderListData([makeSession(A_CHAT)]);

    await act(async () => {
      hook.result.current.handleDelete(A_CHAT);
      await new Promise((res) => setTimeout(res, 0));
    });

    expect(onSessionRemoved).toHaveBeenCalledWith(A_CHAT);
    expect(setSessions).toHaveBeenCalled();
  });

  it("updates the backend when a conversation is pinned within its group", async () => {
    sessionApi.setActiveAgent("agent-a");
    const updateSpy = vi
      .spyOn(chatApi, "updateChat")
      .mockResolvedValue({} as Awaited<ReturnType<typeof chatApi.updateChat>>);
    const listSpy = vi
      .spyOn(api, "listChats")
      .mockResolvedValue([] as ChatSpec[]);
    const { hook } = renderListData([makeSession(A_CHAT)]);

    await act(async () => {
      await hook.result.current.handlePinToggle(A_CHAT, true);
    });

    expect(updateSpy).toHaveBeenCalledWith(A_CHAT, { pinned: true });
    expect(listSpy).toHaveBeenCalledOnce();
  });

  it("refetches the list immediately when the selected agent changes", async () => {
    sessionApi.setActiveAgent("agent-a");
    const listSpy = vi.spyOn(api, "listChats").mockResolvedValue([]);
    const setSessions = vi.fn();

    renderHook(
      () =>
        useSessionListData([], setSessions, {
          active: true,
          currentSessionId: undefined,
          onSessionClick: vi.fn(),
        }),
      { wrapper },
    );
    await waitFor(() => expect(listSpy).toHaveBeenCalledTimes(1));

    act(() => {
      useAgentStore.setState({ selectedAgent: "agent-b" });
    });

    await waitFor(() => expect(listSpy).toHaveBeenCalledTimes(2));
  });
});

// ---------------------------------------------------------------------------
// switchingSessionId lifecycle — regression for #5354
// (a stuck switchingSessionId kept the session list in a "switching" state
// forever, blocking further interaction; the flag must always clear)
// ---------------------------------------------------------------------------
describe("useSessionListData switchingSessionId lifecycle (#5354)", () => {
  const OTHER_CHAT = "44444444-bbbb-4bbb-8bbb-444444444444";

  function renderWithCurrent(currentSessionId: string | undefined) {
    const onSessionClick = vi.fn();
    const setSessions = vi.fn();
    const hook = renderHook(
      ({ current }: { current: string | undefined }) =>
        useSessionListData(
          [makeSession(A_CHAT), makeSession(OTHER_CHAT)],
          setSessions,
          {
            active: false,
            currentSessionId: current,
            onSessionClick,
          },
        ),
      { wrapper, initialProps: { current: currentSessionId } },
    );
    return { hook, onSessionClick };
  }

  it("sets switchingSessionId on click and notifies the parent", async () => {
    sessionApi.setActiveAgent("agent-a");
    const { hook, onSessionClick } = renderWithCurrent(A_CHAT);

    await act(async () => {
      hook.result.current.handleSessionClick(OTHER_CHAT);
    });

    expect(hook.result.current.switchingSessionId).toBe(OTHER_CHAT);
    expect(onSessionClick).toHaveBeenCalledWith(OTHER_CHAT);
  });

  it("does not enter switching state when clicking the already-active session", async () => {
    sessionApi.setActiveAgent("agent-a");
    const { hook, onSessionClick } = renderWithCurrent(A_CHAT);

    await act(async () => {
      hook.result.current.handleSessionClick(A_CHAT);
    });

    expect(hook.result.current.switchingSessionId).toBeNull();
    expect(onSessionClick).not.toHaveBeenCalled();
  });

  it("clears switchingSessionId once currentSessionId settles (normal switch)", async () => {
    sessionApi.setActiveAgent("agent-a");
    const { hook } = renderWithCurrent(A_CHAT);

    await act(async () => {
      hook.result.current.handleSessionClick(OTHER_CHAT);
    });
    expect(hook.result.current.switchingSessionId).toBe(OTHER_CHAT);

    // Navigation completed → URL/session id updated
    hook.rerender({ current: OTHER_CHAT });
    await waitFor(() =>
      expect(hook.result.current.switchingSessionId).toBeNull(),
    );
  });

  it("clears switchingSessionId on the sidebar-switch-done event (failure path)", async () => {
    sessionApi.setActiveAgent("agent-a");
    const { hook } = renderWithCurrent(A_CHAT);

    await act(async () => {
      hook.result.current.handleSessionClick(OTHER_CHAT);
    });
    expect(hook.result.current.switchingSessionId).toBe(OTHER_CHAT);

    // Simple-mode sidebar signals completion via a DOM event even when the
    // session id never changed (e.g. the switch failed).
    await act(async () => {
      window.dispatchEvent(new Event("qwenpaw:sidebar-switch-done"));
    });

    await waitFor(() =>
      expect(hook.result.current.switchingSessionId).toBeNull(),
    );
  });
});
