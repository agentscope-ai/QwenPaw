/**
 * useInboxData — inbox event mapping, polling lifecycle, read/delete
 * bookkeeping. Regression family: inbox badge accuracy and message
 * lifecycle (read state must stay consistent with unread counters).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";

const mocks = vi.hoisted(() => ({
  getInboxEvents: vi.fn(),
  markInboxRead: vi.fn(),
  deleteInboxEvent: vi.fn(),
  agents: [] as unknown[],
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts ? `${key}:${JSON.stringify(opts)}` : key,
    i18n: { language: "en" },
  }),
}));

vi.mock("../../../api", () => ({
  default: {
    getInboxEvents: (...a: unknown[]) => mocks.getInboxEvents(...a),
    markInboxRead: (...a: unknown[]) => mocks.markInboxRead(...a),
    deleteInboxEvent: (...a: unknown[]) => mocks.deleteInboxEvent(...a),
  },
}));

vi.mock("../../../stores/agentStore", () => ({
  useAgentStore: (selector?: (s: { agents: unknown[] }) => unknown) =>
    selector ? selector({ agents: mocks.agents }) : { agents: mocks.agents },
}));

import { useInboxData } from "./useInboxData";

function event(overrides: Record<string, unknown> = {}) {
  return {
    id: "e-1",
    source_type: "cron",
    event_type: "cron",
    title: "Job done",
    body: "Ran successfully duration=1234ms.",
    status: "success",
    severity: "info",
    read: false,
    agent_id: "default",
    created_at: 1000,
    payload: {},
    ...overrides,
  };
}

beforeEach(() => {
  mocks.getInboxEvents.mockReset().mockResolvedValue({
    events: [],
    total: 0,
    unread_count: 0,
  });
  mocks.markInboxRead.mockReset().mockResolvedValue({});
  mocks.deleteInboxEvent.mockReset().mockResolvedValue({});
  mocks.agents = [];
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useInboxData", () => {
  it("loads push messages on mount and sorts newest first", async () => {
    mocks.getInboxEvents.mockResolvedValue({
      events: [
        event({ id: "older", created_at: 1000 }),
        event({ id: "newer", created_at: 2000 }),
      ],
      total: 2,
      unread_count: 2,
    });
    const { result } = renderHook(() => useInboxData());
    await waitFor(() => {
      expect(result.current.pushMessages.length).toBe(2);
    });
    expect(result.current.pushMessages[0].id).toBe("newer");
    expect(result.current.summary.pushMessages).toEqual({
      total: 2,
      unread: 2,
    });
  });

  it("filters out non-push and ACL-pending events", async () => {
    mocks.getInboxEvents.mockResolvedValue({
      events: [
        event({ id: "keep", source_type: "cron" }),
        event({ id: "not-push", source_type: "other" }),
        event({
          id: "acl-pending",
          source_type: "mail",
          payload: { acl_status: "pending" },
        }),
      ],
      total: 3,
    });
    const { result } = renderHook(() => useInboxData());
    await waitFor(() => {
      expect(result.current.pushMessages.length).toBe(1);
    });
    expect(result.current.pushMessages[0].id).toBe("keep");
  });

  it("maps heartbeat events to a status-specific summary", async () => {
    mocks.getInboxEvents.mockResolvedValue({
      events: [
        event({
          id: "hb",
          source_type: "heartbeat",
          status: "success",
          body: "ignored",
        }),
      ],
    });
    const { result } = renderHook(() => useInboxData());
    await waitFor(() => {
      expect(result.current.pushMessages.length).toBe(1);
    });
    const msg = result.current.pushMessages[0];
    expect(msg.content).toBe("inbox.heartbeatSuccess");
    expect(msg.channelType).toBe("heartbeat");
    expect(msg.channelName).toBe("Heartbeat");
  });

  it("strips execution-time text from cron message bodies", async () => {
    mocks.getInboxEvents.mockResolvedValue({
      events: [event({ id: "c", body: "All good duration=1234ms." })],
    });
    const { result } = renderHook(() => useInboxData());
    await waitFor(() => {
      expect(result.current.pushMessages.length).toBe(1);
    });
    expect(result.current.pushMessages[0].content).toBe("All good");
  });

  it("marks error severity as high priority and error body text too", async () => {
    mocks.getInboxEvents.mockResolvedValue({
      events: [
        event({ id: "sev", severity: "error", body: "boom" }),
        event({ id: "body", body: "❌ something broke" }),
      ],
    });
    const { result } = renderHook(() => useInboxData());
    await waitFor(() => {
      expect(result.current.pushMessages.length).toBe(2);
    });
    const byId = Object.fromEntries(
      result.current.pushMessages.map((m) => [m.id, m]),
    );
    expect(byId.sev.metadata!.priority).toBe("high");
    expect(byId.body.metadata!.priority).toBe("high");
  });

  it("maps skill auto-sync events with a sync summary", async () => {
    mocks.getInboxEvents.mockResolvedValue({
      events: [
        event({
          id: "sync",
          source_type: "skill_autoupdate",
          event_type: "auto_sync",
          body: "fallback",
          payload: {
            synced: [{ skill: "weather", agents: ["a1"] }],
            failed: [{ skill: "broken", agents: ["a2"] }],
          },
        }),
      ],
    });
    const { result } = renderHook(() => useInboxData());
    await waitFor(() => {
      expect(result.current.pushMessages.length).toBe(1);
    });
    const msg = result.current.pushMessages[0];
    expect(msg.title).toBe("inbox.skillAutoSyncTitle");
    expect(msg.content).toContain("inbox.skillAutoSynced");
    expect(msg.content).toContain("inbox.skillAutoSyncFailed");
    expect(msg.channelType).toBe("skill");
  });

  it("maps builtin auto-update events separately from auto-sync", async () => {
    mocks.getInboxEvents.mockResolvedValue({
      events: [
        event({
          id: "upd",
          source_type: "skill_autoupdate",
          event_type: "auto_update",
          payload: {
            pool_updated: [{ skill: "s1", from_version: "1", to_version: "2" }],
          },
        }),
      ],
    });
    const { result } = renderHook(() => useInboxData());
    await waitFor(() => {
      expect(result.current.pushMessages.length).toBe(1);
    });
    const msg = result.current.pushMessages[0];
    expect(msg.title).toBe("inbox.skillBuiltinAutoUpdateTitle");
    expect(msg.content).toContain("inbox.skillBuiltinUpdated");
  });

  it("resolves the agent display name for known agents", async () => {
    // getAgentDisplayName reads agent.name (fallback: id)
    mocks.agents = [{ id: "agent-9", name: "Help Bot" }];
    mocks.getInboxEvents.mockResolvedValue({
      events: [event({ id: "x", agent_id: "agent-9" })],
    });
    const { result } = renderHook(() => useInboxData());
    await waitFor(() => {
      expect(result.current.pushMessages.length).toBe(1);
    });
    expect(result.current.pushMessages[0].sender.username).toBe("Help Bot");
  });

  it("falls back to the default agent display name", async () => {
    mocks.getInboxEvents.mockResolvedValue({
      events: [event({ id: "x", agent_id: "default" })],
    });
    const { result } = renderHook(() => useInboxData());
    await waitFor(() => {
      expect(result.current.pushMessages.length).toBe(1);
    });
    expect(result.current.pushMessages[0].sender.username).toBe(
      "agent.defaultDisplayName",
    );
  });

  it("falls back to the raw agent id for unknown agents", async () => {
    mocks.getInboxEvents.mockResolvedValue({
      events: [event({ id: "x", agent_id: "mystery-agent" })],
    });
    const { result } = renderHook(() => useInboxData());
    await waitFor(() => {
      expect(result.current.pushMessages.length).toBe(1);
    });
    expect(result.current.pushMessages[0].sender.username).toBe(
      "mystery-agent",
    );
  });

  it("polls on an interval while visible", async () => {
    vi.useFakeTimers();
    mocks.getInboxEvents.mockResolvedValue({ events: [], total: 0 });
    renderHook(() => useInboxData());
    await act(async () => {
      await Promise.resolve();
    });
    const initialCalls = mocks.getInboxEvents.mock.calls.length;
    await act(async () => {
      vi.advanceTimersByTime(6000);
    });
    expect(mocks.getInboxEvents.mock.calls.length).toBe(initialCalls + 1);
    vi.useRealTimers();
  });

  it("marks a single message as read and decrements unread", async () => {
    mocks.getInboxEvents.mockResolvedValue({
      events: [event({ id: "m1", read: false })],
      total: 1,
      unread_count: 1,
    });
    const { result } = renderHook(() => useInboxData());
    await waitFor(() => {
      expect(result.current.summary.pushMessages.unread).toBe(1);
    });
    act(() => {
      result.current.markMessageAsRead("m1");
    });
    expect(mocks.markInboxRead).toHaveBeenCalledWith({ event_ids: ["m1"] });
    expect(result.current.pushMessages[0].read).toBe(true);
    expect(result.current.summary.pushMessages.unread).toBe(0);
  });

  it("marks all messages as read via the backend all flag", async () => {
    mocks.getInboxEvents.mockResolvedValue({
      events: [event({ id: "m1" }), event({ id: "m2", read: true })],
      total: 2,
      unread_count: 1,
    });
    const { result } = renderHook(() => useInboxData());
    await waitFor(() => {
      expect(result.current.pushMessages.length).toBe(2);
    });
    let count = -1;
    await act(async () => {
      count = await result.current.markAllMessagesAsRead();
    });
    expect(mocks.markInboxRead).toHaveBeenCalledWith({ all: true });
    expect(count).toBe(1);
    expect(result.current.summary.pushMessages.unread).toBe(0);
    expect(result.current.pushMessages.every((m) => m.read)).toBe(true);
  });

  it("deletes selected messages from the list", async () => {
    mocks.getInboxEvents.mockResolvedValue({
      events: [event({ id: "a", read: false }), event({ id: "b", read: true })],
      total: 2,
      unread_count: 1,
    });
    const { result } = renderHook(() => useInboxData());
    await waitFor(() => {
      expect(result.current.pushMessages.length).toBe(2);
    });
    await act(async () => {
      await result.current.deleteMessages(["a", " a ", ""]);
    });
    expect(mocks.deleteInboxEvent).toHaveBeenCalledWith("a");
    expect(result.current.pushMessages.map((m) => m.id)).toEqual(["b"]);
  });

  it("re-syncs list and badge from server data on the next poll after delete", async () => {
    vi.useFakeTimers();
    mocks.getInboxEvents.mockResolvedValue({
      events: [event({ id: "a", read: false }), event({ id: "b", read: true })],
      total: 2,
      unread_count: 1,
    });
    const { result } = renderHook(() => useInboxData());
    await act(async () => {
      for (let i = 0; i < 5; i += 1) await Promise.resolve();
    });
    expect(result.current.pushMessages.length).toBe(2);
    // Server state after the deletion: only message b remains.
    mocks.getInboxEvents.mockResolvedValue({
      events: [event({ id: "b", read: true })],
      total: 1,
      unread_count: 0,
    });
    await act(async () => {
      await result.current.deleteMessages(["a"]);
    });
    expect(result.current.pushMessages.map((m) => m.id)).toEqual(["b"]);
    // The 6s poll rewrites list and badge from the server response,
    // independent of local setState updater timing.
    await act(async () => {
      vi.advanceTimersByTime(6000);
    });
    expect(result.current.summary.pushMessages).toEqual({
      total: 1,
      unread: 0,
    });
    expect(result.current.pushMessages.map((m) => m.id)).toEqual(["b"]);
    vi.useRealTimers();
  });

  it("returns zero deleted for an empty id list without API calls", async () => {
    const { result } = renderHook(() => useInboxData());
    let deleted = -1;
    await act(async () => {
      deleted = await result.current.deleteMessages(["", "  "]);
    });
    expect(deleted).toBe(0);
    expect(mocks.deleteInboxEvent).not.toHaveBeenCalled();
  });

  it("keeps state when fetching inbox events fails", async () => {
    mocks.getInboxEvents.mockRejectedValue(new Error("offline"));
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const { result } = renderHook(() => useInboxData());
    await act(async () => {
      await Promise.resolve();
    });
    expect(result.current.pushMessages).toEqual([]);
    expect(errSpy).toHaveBeenCalled();
    errSpy.mockRestore();
  });

  it("keeps polling across visibility changes", async () => {
    vi.useFakeTimers();
    mocks.getInboxEvents.mockResolvedValue({ events: [], total: 0 });
    renderHook(() => useInboxData());
    await act(async () => {
      await Promise.resolve();
    });
    const callsBefore = mocks.getInboxEvents.mock.calls.length;
    act(() => {
      Object.defineProperty(document, "visibilityState", {
        value: "hidden",
        configurable: true,
      });
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await act(async () => {
      vi.advanceTimersByTime(12000);
    });
    // Polling stopped while hidden
    expect(mocks.getInboxEvents.mock.calls.length).toBe(callsBefore);
    act(() => {
      Object.defineProperty(document, "visibilityState", {
        value: "visible",
        configurable: true,
      });
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await act(async () => {
      await Promise.resolve();
      vi.advanceTimersByTime(6000);
    });
    // Refreshed on visible + one poll tick
    expect(mocks.getInboxEvents.mock.calls.length).toBeGreaterThanOrEqual(
      callsBefore + 2,
    );
    vi.useRealTimers();
  });
});
