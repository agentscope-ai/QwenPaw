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
import { useMessageQueueStore } from "../../../../stores/messageQueueStore";
import {
  useSessionListData,
  getBackendId,
  formatCreatedAt,
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
    vi.spyOn(api, "listChats").mockResolvedValue([] as unknown as ChatSpec[]);

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
      .mockResolvedValue([] as unknown as ChatSpec[]);
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

// ---------------------------------------------------------------------------
// Pure helpers: getBackendId / formatCreatedAt
// ---------------------------------------------------------------------------
describe("getBackendId", () => {
  it("prefers realId over the (possibly local) id", () => {
    const s = {
      id: "1724000000000-abc123",
      realId: "real-uuid",
    } as ExtendedChatSession;
    expect(getBackendId(s)).toBe("real-uuid");
  });

  it("returns null for local timestamp ids without realId", () => {
    const s = { id: "1724000000000-abc123" } as ExtendedChatSession;
    expect(getBackendId(s)).toBeNull();
  });

  it("returns the id itself for backend uuids", () => {
    const s = makeSession(A_CHAT);
    expect(getBackendId(s)).toBe(A_CHAT);
  });
});

describe("formatCreatedAt", () => {
  const pad = (n: number) => String(n).padStart(2, "0");
  const localFormat = (d: Date) =>
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(
      d.getHours(),
    )}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;

  it("formats an ISO timestamp in local time", () => {
    const raw = "2026-08-31T07:04:05Z";
    expect(formatCreatedAt(raw)).toBe(localFormat(new Date(raw)));
  });

  it("returns empty string for null/undefined/empty input", () => {
    expect(formatCreatedAt(null)).toBe("");
    expect(formatCreatedAt(undefined)).toBe("");
    expect(formatCreatedAt("")).toBe("");
  });

  it("returns empty string for unparseable dates", () => {
    expect(formatCreatedAt("not-a-date")).toBe("");
  });
});

// ---------------------------------------------------------------------------
// List shaping: filtering local-only ids, hiding archived, sorting by time
// ---------------------------------------------------------------------------
describe("useSessionListData list shaping", () => {
  it("drops local-format ids without realId, hides archived, sorts newest first", () => {
    sessionApi.setActiveAgent("agent-a");
    const old = {
      ...makeSession("old-uuid"),
      updatedAt: "2026-08-31T10:00:00Z",
    };
    const fresh = {
      ...makeSession("new-uuid"),
      updatedAt: "2026-08-31T12:00:00Z",
    };
    const archived = {
      ...makeSession("arch-uuid"),
      updatedAt: "2026-08-31T23:00:00Z",
      archived: true,
    };
    const localOnly = { id: "1724000000000-zzz999" } as ExtendedChatSession;
    const localWithReal = {
      id: "1724000000001-yyy888",
      realId: "real-uuid",
      updatedAt: "2026-08-31T09:00:00Z",
    } as unknown as ExtendedChatSession;
    const timeless = makeSession("timeless-uuid");

    const { hook } = renderListData([
      old,
      fresh,
      archived,
      localOnly,
      localWithReal,
      timeless,
    ]);

    expect(hook.result.current.sortedSessions.map((s) => s.id)).toEqual([
      "new-uuid",
      "old-uuid",
      "1724000000001-yyy888",
      "timeless-uuid",
    ]);
  });
});

// ---------------------------------------------------------------------------
// Rename flow: start → change → submit/cancel
// ---------------------------------------------------------------------------
describe("useSessionListData rename flow", () => {
  beforeEach(() => {
    sessionApi.setActiveAgent("agent-a");
  });

  it("submits a rename to the backend and refreshes the list", async () => {
    const updateSpy = vi
      .spyOn(chatApi, "updateChat")
      .mockResolvedValue({} as Awaited<ReturnType<typeof chatApi.updateChat>>);
    const listSpy = vi.spyOn(api, "listChats").mockResolvedValue([]);
    const { hook } = renderListData([makeSession(A_CHAT)]);

    act(() => {
      hook.result.current.handleEditStart(A_CHAT, "Old Name");
    });
    expect(hook.result.current.editingSessionId).toBe(A_CHAT);
    expect(hook.result.current.editValue).toBe("Old Name");

    act(() => {
      hook.result.current.handleEditChange("  New Name  ");
    });

    await act(async () => {
      await hook.result.current.handleEditSubmit();
    });

    expect(updateSpy).toHaveBeenCalledWith(A_CHAT, { name: "New Name" });
    expect(listSpy).toHaveBeenCalled();
    expect(hook.result.current.editingSessionId).toBeNull();
    expect(hook.result.current.editValue).toBe("");
  });

  it("skips the backend call when the new name is blank", async () => {
    const updateSpy = vi.spyOn(chatApi, "updateChat");
    vi.spyOn(api, "listChats").mockResolvedValue([]);
    const { hook } = renderListData([makeSession(A_CHAT)]);

    act(() => {
      hook.result.current.handleEditStart(A_CHAT, "Old Name");
      hook.result.current.handleEditChange("   ");
    });
    await act(async () => {
      await hook.result.current.handleEditSubmit();
    });

    expect(updateSpy).not.toHaveBeenCalled();
    expect(hook.result.current.editingSessionId).toBeNull();
  });

  it("cancelling a rename clears the edit state without backend calls", () => {
    const updateSpy = vi.spyOn(chatApi, "updateChat");
    const { hook } = renderListData([makeSession(A_CHAT)]);

    act(() => {
      hook.result.current.handleEditStart(A_CHAT, "Old Name");
      hook.result.current.handleEditCancel();
    });

    expect(updateSpy).not.toHaveBeenCalled();
    expect(hook.result.current.editingSessionId).toBeNull();
    expect(hook.result.current.editValue).toBe("");
  });

  it("does nothing on submit when no rename is in progress", async () => {
    const updateSpy = vi.spyOn(chatApi, "updateChat");
    const { hook } = renderListData([makeSession(A_CHAT)]);
    await act(async () => {
      await hook.result.current.handleEditSubmit();
    });
    expect(updateSpy).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// Archive toggle: archive/unarchive, current-session navigation, error path
// ---------------------------------------------------------------------------
describe("useSessionListData archive toggle", () => {
  beforeEach(() => {
    sessionApi.setActiveAgent("agent-a");
  });

  it("archives an active chat, shows feedback and refreshes", async () => {
    const archiveSpy = vi
      .spyOn(chatApi, "archiveChat")
      .mockResolvedValue({} as Awaited<ReturnType<typeof chatApi.archiveChat>>);
    vi.spyOn(api, "listChats").mockResolvedValue([]);
    const { hook } = renderListData([makeSession(A_CHAT)]);

    await act(async () => {
      await hook.result.current.handleArchiveToggle(A_CHAT);
    });

    expect(archiveSpy).toHaveBeenCalledWith(A_CHAT);
  });

  it("unarchives an archived chat instead", async () => {
    const unarchiveSpy = vi
      .spyOn(chatApi, "unarchiveChat")
      .mockResolvedValue(
        {} as Awaited<ReturnType<typeof chatApi.unarchiveChat>>,
      );
    const archiveSpy = vi.spyOn(chatApi, "archiveChat");
    vi.spyOn(api, "listChats").mockResolvedValue([]);
    const archived = { ...makeSession(A_CHAT), archived: true };
    const { hook } = renderListData([archived]);

    await act(async () => {
      await hook.result.current.handleArchiveToggle(A_CHAT);
    });

    expect(unarchiveSpy).toHaveBeenCalledWith(A_CHAT);
    expect(archiveSpy).not.toHaveBeenCalled();
  });

  it("navigates to a new chat when the current session gets archived", async () => {
    vi.spyOn(chatApi, "archiveChat").mockResolvedValue(
      {} as Awaited<ReturnType<typeof chatApi.archiveChat>>,
    );
    vi.spyOn(api, "listChats").mockResolvedValue([]);
    const newChatListener = vi.fn();
    window.addEventListener("qwenpaw:sidebar-new-chat", newChatListener);
    const { hook } = renderListData([makeSession(A_CHAT)]);

    await act(async () => {
      await hook.result.current.handleArchiveToggle(A_CHAT);
    });

    expect(newChatListener).toHaveBeenCalled();
    window.removeEventListener("qwenpaw:sidebar-new-chat", newChatListener);
  });

  it("reports an error when the archive call fails", async () => {
    vi.spyOn(chatApi, "archiveChat").mockRejectedValue(new Error("boom"));
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const { hook } = renderListData([makeSession(A_CHAT)]);

    await act(async () => {
      await hook.result.current.handleArchiveToggle(A_CHAT);
    });

    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  it("does nothing for a session without a backend id", async () => {
    const archiveSpy = vi.spyOn(chatApi, "archiveChat");
    const localOnly = { id: "1724000000000-zzz999" } as ExtendedChatSession;
    const { hook } = renderListData([localOnly]);

    await act(async () => {
      await hook.result.current.handleArchiveToggle("1724000000000-zzz999");
    });

    expect(archiveSpy).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// Pin toggle error path
// ---------------------------------------------------------------------------
describe("useSessionListData pin toggle failure", () => {
  it("reports an error and keeps going when pinning fails", async () => {
    sessionApi.setActiveAgent("agent-a");
    vi.spyOn(chatApi, "updateChat").mockRejectedValue(new Error("nope"));
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const { hook } = renderListData([makeSession(A_CHAT)]);

    await act(async () => {
      await hook.result.current.handlePinToggle(A_CHAT, true);
    });

    expect(consoleSpy).toHaveBeenCalled();
    expect(hook.result.current.editingSessionId).toBeNull();
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// Delete extras: dual-key message-queue cleanup + current-session navigation
// ---------------------------------------------------------------------------
describe("useSessionListData delete extras", () => {
  beforeEach(() => {
    sessionApi.setActiveAgent("agent-a");
  });

  it("clears approval level and message queue under both ids, then navigates when the current chat is gone", async () => {
    const REAL = "55555555-cccc-4ccc-8ccc-555555555555";
    vi.spyOn(chatApi, "deleteChat").mockResolvedValue(
      {} as Awaited<ReturnType<typeof chatApi.deleteChat>>,
    );
    vi.spyOn(api, "listChats").mockResolvedValue([]);
    const lsSpy = vi.spyOn(window.localStorage, "removeItem");
    const clearSpy = vi.spyOn(useMessageQueueStore.getState(), "clear");
    const newChatListener = vi.fn();
    window.addEventListener("qwenpaw:sidebar-new-chat", newChatListener);

    const withReal = {
      ...makeSession(A_CHAT),
      realId: REAL,
    } as ExtendedChatSession;
    const { hook } = renderListData([withReal]);

    await act(async () => {
      hook.result.current.handleDelete(A_CHAT);
      await new Promise((res) => setTimeout(res, 0));
    });

    expect(chatApi.deleteChat).toHaveBeenCalledWith(REAL);
    expect(lsSpy).toHaveBeenCalledWith(`approval_level-${A_CHAT}`);
    expect(clearSpy).toHaveBeenCalledWith(A_CHAT);
    expect(clearSpy).toHaveBeenCalledWith(REAL);
    expect(newChatListener).toHaveBeenCalled();

    window.removeEventListener("qwenpaw:sidebar-new-chat", newChatListener);
    lsSpy.mockRestore();
    clearSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// Context menu: items reflect session state and delegate to handlers
// ---------------------------------------------------------------------------
describe("useSessionListData context menu", () => {
  beforeEach(() => {
    sessionApi.setActiveAgent("agent-a");
  });

  const mouseEvent = () =>
    ({
      clientX: 10,
      clientY: 20,
      preventDefault: vi.fn(),
      stopPropagation: vi.fn(),
    }) as unknown as React.MouseEvent;

  it("opens the menu and builds the full item set for the target session", () => {
    const { hook } = renderListData([makeSession(A_CHAT)]);

    expect(hook.result.current.contextMenuItems).toEqual([]);

    act(() => {
      hook.result.current.handleItemContextMenu(A_CHAT, mouseEvent());
    });

    expect(hook.result.current.contextMenu.visible).toBe(true);
    expect(hook.result.current.contextMenu.x).toBe(10);
    expect(hook.result.current.contextMenu.y).toBe(20);
    expect(hook.result.current.contextMenuItems.map((i) => i.key)).toEqual([
      "open",
      "rename",
      "pin",
      "archive",
      "divider-1",
      "delete",
    ]);
  });

  it("offers Unpin/Unarchive labels for pinned/archived sessions", () => {
    const pinned = {
      ...makeSession(A_CHAT),
      pinned: true,
      archived: true,
    } as ExtendedChatSession;
    const { hook } = renderListData([pinned]);

    act(() => {
      hook.result.current.handleItemContextMenu(A_CHAT, mouseEvent());
    });

    const pin = hook.result.current.contextMenuItems.find(
      (i) => i.key === "pin",
    );
    const archive = hook.result.current.contextMenuItems.find(
      (i) => i.key === "archive",
    );
    // t() falls back to the default string when i18next is not initialized
    expect(pin?.label).toBe("Unpin");
    expect(archive?.label).toBe("Unarchive");
  });

  it("menu actions delegate to the underlying handlers", async () => {
    const onSessionClick = vi.fn();
    const setSessions = vi.fn();
    vi.spyOn(api, "listChats").mockResolvedValue([]);
    const updateSpy = vi
      .spyOn(chatApi, "updateChat")
      .mockResolvedValue({} as Awaited<ReturnType<typeof chatApi.updateChat>>);

    const hook = renderHook(
      () =>
        useSessionListData([makeSession(A_CHAT)], setSessions, {
          active: false,
          currentSessionId: undefined,
          onSessionClick,
        }),
      { wrapper },
    );

    act(() => {
      hook.result.current.handleItemContextMenu(A_CHAT, mouseEvent());
    });

    const item = (key: string) =>
      hook.result.current.contextMenuItems.find((i) => i.key === key);

    // Open → notifies parent (and since it is not current, enters switching)
    act(() => {
      item("open")?.onClick?.();
    });
    expect(onSessionClick).toHaveBeenCalledWith(A_CHAT);

    // Rename → enters edit mode prefilled with the session name
    act(() => {
      item("rename")?.onClick?.();
    });
    expect(hook.result.current.editingSessionId).toBe(A_CHAT);
    expect(hook.result.current.editValue).toBe(A_CHAT);

    // Pin → backend update with the inverted pinned flag
    await act(async () => {
      await item("pin")?.onClick?.();
    });
    expect(updateSpy).toHaveBeenCalledWith(A_CHAT, { pinned: true });
  });

  it("falls back to 'New Chat' when renaming a session without a name", () => {
    const nameless = {
      ...makeSession(A_CHAT),
      name: "",
    } as ExtendedChatSession;
    const { hook } = renderListData([nameless]);

    act(() => {
      hook.result.current.handleItemContextMenu(A_CHAT, mouseEvent());
    });
    act(() => {
      hook.result.current.contextMenuItems
        .find((i) => i.key === "rename")
        ?.onClick?.();
    });

    expect(hook.result.current.editValue).toBe("New Chat");
  });
});

// ---------------------------------------------------------------------------
// Polling: initial fetch, 3s interval, no-op skip, switch pause, errors
// ---------------------------------------------------------------------------
describe("useSessionListData polling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    sessionApi.setActiveAgent("agent-a");
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  function renderActive(setSessions: (s: unknown[]) => void) {
    return renderHook(
      () =>
        useSessionListData([], setSessions, {
          active: true,
          currentSessionId: undefined,
          onSessionClick: vi.fn(),
        }),
      { wrapper },
    );
  }

  it("fetches on activation, skips identical updates, applies changed lists", async () => {
    const listSpy = vi
      .spyOn(api, "listChats")
      .mockResolvedValue([makeSession("s1")] as unknown as ChatSpec[]);
    const setSessions = vi.fn();
    renderActive(setSessions);

    // Initial fetch settles
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(setSessions).toHaveBeenCalledTimes(1);
    expect(
      setSessions.mock.calls[0][0].map((s: ExtendedChatSession) => s.id),
    ).toEqual(["s1"]);

    // Next poll returns the same list → no redundant state update
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(listSpy.mock.calls.length).toBeGreaterThanOrEqual(2);
    expect(setSessions).toHaveBeenCalledTimes(1);

    // A changed list is applied
    listSpy.mockResolvedValue([makeSession("s2")] as unknown as ChatSpec[]);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(setSessions).toHaveBeenCalledTimes(2);
    expect(
      setSessions.mock.calls[1][0].map((s: ExtendedChatSession) => s.id),
    ).toEqual(["s2"]);
  });

  it("pauses polling while a session switch is in flight", async () => {
    const listSpy = vi.spyOn(api, "listChats").mockResolvedValue([]);
    const setSessions = vi.fn();
    renderActive(setSessions);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    const callsAfterInitial = listSpy.mock.calls.length;

    sessionApi.isSessionSwitching = true;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(9000);
    });
    expect(listSpy.mock.calls.length).toBe(callsAfterInitial);
    sessionApi.isSessionSwitching = false;
  });

  it("keeps polling after a failed fetch and reports the initial failure", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const listSpy = vi
      .spyOn(api, "listChats")
      .mockRejectedValue(new Error("down"));
    const setSessions = vi.fn();
    const hook = renderActive(setSessions);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(consoleSpy).toHaveBeenCalled();
    expect(hook.result.current.loading).toBe(false);

    // Polling errors are swallowed silently and polling continues
    consoleSpy.mockClear();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(consoleSpy).not.toHaveBeenCalled();

    // Recovery: next poll succeeds and updates the list
    listSpy.mockResolvedValue([makeSession("s1")] as unknown as ChatSpec[]);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(setSessions).toHaveBeenCalledTimes(1);
    consoleSpy.mockRestore();
  });

  it("does not fetch while inactive", async () => {
    const listSpy = vi.spyOn(api, "listChats").mockResolvedValue([]);
    const setSessions = vi.fn();
    renderHook(
      () =>
        useSessionListData([], setSessions, {
          active: false,
          currentSessionId: undefined,
          onSessionClick: vi.fn(),
        }),
      { wrapper },
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
    });
    expect(listSpy).not.toHaveBeenCalled();
    expect(setSessions).not.toHaveBeenCalled();
  });

  it("stops polling after deactivation", async () => {
    const listSpy = vi.spyOn(api, "listChats").mockResolvedValue([]);
    const setSessions = vi.fn();
    const hook = renderHook(
      ({ active }: { active: boolean }) =>
        useSessionListData([], setSessions, {
          active,
          currentSessionId: undefined,
          onSessionClick: vi.fn(),
        }),
      { wrapper, initialProps: { active: true } },
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    hook.rerender({ active: false });
    const callsAfterDeactivate = listSpy.mock.calls.length;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(9000);
    });
    expect(listSpy.mock.calls.length).toBe(callsAfterDeactivate);
  });
});

// ---------------------------------------------------------------------------
// Owner guards on the refetch paths + remaining sort/delete edges
// ---------------------------------------------------------------------------
describe("useSessionListData owner guards and misc edges", () => {
  beforeEach(() => {
    sessionApi.setActiveAgent("agent-a");
  });

  it("refreshSessions drops a list fetched after an agent switch", async () => {
    const dList = deferred<ChatSpec[]>();
    const listSpy = vi.spyOn(api, "listChats").mockReturnValue(dList.promise);
    const { hook, setSessions } = renderListData([]);

    let pending!: unknown;
    act(() => {
      pending = hook.result.current.refreshSessions();
    });
    sessionApi.setActiveAgent("agent-b");
    dList.resolve([makeSession("late")] as unknown as ChatSpec[]);
    await act(async () => {
      await pending;
    });

    expect(listSpy).toHaveBeenCalled();
    expect(setSessions).not.toHaveBeenCalled();
  });

  it("refreshSessions reports a fetch failure", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    vi.spyOn(api, "listChats").mockRejectedValue(new Error("down"));
    const { hook } = renderListData([]);

    await act(async () => {
      await hook.result.current.refreshSessions();
    });

    expect(consoleSpy).toHaveBeenCalledWith(
      "useSessionListData: failed to fetch sessions",
      expect.any(Error),
    );
    consoleSpy.mockRestore();
  });

  it("sorts sessions with a timestamp ahead of sessions without any", () => {
    const withTime = {
      ...makeSession("has-time"),
      updatedAt: "2026-01-02T00:00:00Z",
    } as ExtendedChatSession;
    const noTime = makeSession("no-time");

    // Both comparison directions so each empty-time branch is exercised.
    const asc = renderListData([noTime, withTime]);
    expect(asc.hook.result.current.sortedSessions.map((s) => s.id)).toEqual([
      "has-time",
      "no-time",
    ]);

    const desc = renderListData([withTime, noTime]);
    expect(desc.hook.result.current.sortedSessions.map((s) => s.id)).toEqual([
      "has-time",
      "no-time",
    ]);
  });

  it("skips post-delete republish when the owner switches during the fresh fetch", async () => {
    const onSessionRemoved = vi.fn();
    sessionApi.onSessionRemoved = onSessionRemoved;
    vi.spyOn(chatApi, "deleteChat").mockResolvedValue(
      {} as Awaited<ReturnType<typeof chatApi.deleteChat>>,
    );
    const dList = deferred<ChatSpec[]>();
    const listSpy = vi.spyOn(api, "listChats").mockReturnValue(dList.promise);
    const { hook, setSessions } = renderListData([makeSession(A_CHAT)]);

    let pending!: unknown;
    act(() => {
      pending = hook.result.current.handleDelete(A_CHAT);
    });
    // The first ownership check passes, then the user switches mid-refetch.
    await act(async () => {
      await new Promise((res) => setTimeout(res, 0));
    });
    expect(onSessionRemoved).toHaveBeenCalled();

    sessionApi.setActiveAgent("agent-b");
    dList.resolve([makeSession("leftover")] as unknown as ChatSpec[]);
    await act(async () => {
      await pending;
    });

    expect(listSpy).toHaveBeenCalled();
    expect(setSessions).not.toHaveBeenCalled();
  });

  it("does not navigate away when the current chat survives deletion of another chat", async () => {
    vi.spyOn(chatApi, "deleteChat").mockResolvedValue(
      {} as Awaited<ReturnType<typeof chatApi.deleteChat>>,
    );
    vi.spyOn(api, "listChats").mockResolvedValue([
      makeSession(A_CHAT),
    ] as unknown as ChatSpec[]);
    const newChatListener = vi.fn();
    window.addEventListener("qwenpaw:sidebar-new-chat", newChatListener);

    const { hook } = renderListData([
      makeSession(A_CHAT),
      makeSession("other-chat"),
    ]);

    await act(async () => {
      hook.result.current.handleDelete("other-chat");
      await new Promise((res) => setTimeout(res, 0));
    });

    expect(newChatListener).not.toHaveBeenCalled();
    window.removeEventListener("qwenpaw:sidebar-new-chat", newChatListener);
  });

  it("matches the current chat by realId when deciding post-delete navigation", async () => {
    vi.spyOn(chatApi, "deleteChat").mockResolvedValue(
      {} as Awaited<ReturnType<typeof chatApi.deleteChat>>,
    );
    // The fresh list only knows the session by a different id whose realId
    // equals the URL chatId — the chat still exists, so no navigation.
    const freshWithRealId = {
      ...makeSession("fresh-id"),
      realId: A_CHAT,
    } as ExtendedChatSession;
    vi.spyOn(sessionApi, "getSessionList").mockResolvedValue([
      freshWithRealId,
    ] as Awaited<ReturnType<typeof sessionApi.getSessionList>>);
    const newChatListener = vi.fn();
    window.addEventListener("qwenpaw:sidebar-new-chat", newChatListener);

    const { hook } = renderListData([makeSession("other-chat")]);

    await act(async () => {
      hook.result.current.handleDelete("other-chat");
      await new Promise((res) => setTimeout(res, 0));
    });

    expect(newChatListener).not.toHaveBeenCalled();
    window.removeEventListener("qwenpaw:sidebar-new-chat", newChatListener);
  });

  it("handleEditSubmit skips the refetch when the owner changed mid-rename", async () => {
    const dUpdate = deferred<Awaited<ReturnType<typeof chatApi.updateChat>>>();
    const updateSpy = vi
      .spyOn(chatApi, "updateChat")
      .mockReturnValue(dUpdate.promise);
    const listSpy = vi.spyOn(api, "listChats");
    const { hook } = renderListData([makeSession(A_CHAT)]);

    act(() => {
      hook.result.current.handleEditStart(A_CHAT, "Old");
      hook.result.current.handleEditChange("New");
    });

    let pending!: unknown;
    act(() => {
      pending = hook.result.current.handleEditSubmit();
    });
    sessionApi.setActiveAgent("agent-b");
    dUpdate.resolve({} as Awaited<ReturnType<typeof chatApi.updateChat>>);
    await act(async () => {
      await pending;
    });

    expect(updateSpy).toHaveBeenCalledWith(A_CHAT, { name: "New" });
    expect(listSpy).not.toHaveBeenCalled();
  });

  it("handleArchiveToggle skips feedback and refetch after an owner switch", async () => {
    const dArchive =
      deferred<Awaited<ReturnType<typeof chatApi.archiveChat>>>();
    vi.spyOn(chatApi, "archiveChat").mockReturnValue(dArchive.promise);
    const listSpy = vi.spyOn(api, "listChats");
    const { hook } = renderListData([makeSession(A_CHAT)]);

    let pending!: unknown;
    act(() => {
      pending = hook.result.current.handleArchiveToggle(A_CHAT);
    });
    sessionApi.setActiveAgent("agent-b");
    dArchive.resolve({} as Awaited<ReturnType<typeof chatApi.archiveChat>>);
    await act(async () => {
      await pending;
    });

    expect(listSpy).not.toHaveBeenCalled();
  });

  it("handlePinToggle ignores sessions without a backend id", async () => {
    const updateSpy = vi.spyOn(chatApi, "updateChat");
    const localOnly = { id: "1724000000000-abc123" } as ExtendedChatSession;
    const { hook } = renderListData([localOnly]);

    await act(async () => {
      await hook.result.current.handlePinToggle("1724000000000-abc123", true);
    });

    expect(updateSpy).not.toHaveBeenCalled();
  });

  it("handlePinToggle skips the refetch when the owner changed mid-update", async () => {
    const dUpdate = deferred<Awaited<ReturnType<typeof chatApi.updateChat>>>();
    vi.spyOn(chatApi, "updateChat").mockReturnValue(dUpdate.promise);
    const listSpy = vi.spyOn(api, "listChats");
    const { hook } = renderListData([makeSession(A_CHAT)]);

    let pending!: unknown;
    act(() => {
      pending = hook.result.current.handlePinToggle(A_CHAT, true);
    });
    sessionApi.setActiveAgent("agent-b");
    dUpdate.resolve({} as Awaited<ReturnType<typeof chatApi.updateChat>>);
    await act(async () => {
      await pending;
    });

    expect(listSpy).not.toHaveBeenCalled();
  });

  it("context menu archive and delete items invoke their handlers", async () => {
    vi.spyOn(chatApi, "archiveChat").mockResolvedValue(
      {} as Awaited<ReturnType<typeof chatApi.archiveChat>>,
    );
    vi.spyOn(chatApi, "deleteChat").mockResolvedValue(
      {} as Awaited<ReturnType<typeof chatApi.deleteChat>>,
    );
    vi.spyOn(api, "listChats").mockResolvedValue([]);

    const mouseEvent = () =>
      ({
        clientX: 1,
        clientY: 2,
        preventDefault: vi.fn(),
        stopPropagation: vi.fn(),
      }) as unknown as React.MouseEvent;

    const { hook } = renderListData([makeSession(A_CHAT)]);

    act(() => {
      hook.result.current.handleItemContextMenu(A_CHAT, mouseEvent());
    });

    const item = (key: string) =>
      hook.result.current.contextMenuItems.find((i) => i.key === key);

    await act(async () => {
      await item("archive")?.onClick?.();
    });
    expect(chatApi.archiveChat).toHaveBeenCalledWith(A_CHAT);

    await act(async () => {
      await item("delete")?.onClick?.();
      await new Promise((res) => setTimeout(res, 0));
    });
    expect(chatApi.deleteChat).toHaveBeenCalledWith(A_CHAT);
  });
});
