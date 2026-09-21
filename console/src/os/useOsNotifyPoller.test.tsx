import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { InboxEvent } from "../api/modules/console";
import { useOsNotify } from "./osNotifyStore";
import { INBOX_CHANGED_EVENT } from "../utils/inboxEvents";

const { mockGetInboxEvents, mockGetPushMessages } = vi.hoisted(() => ({
  mockGetInboxEvents: vi.fn(),
  mockGetPushMessages: vi.fn(),
}));

vi.mock("../api", () => ({
  default: {
    getInboxEvents: mockGetInboxEvents,
    getPushMessages: mockGetPushMessages,
  },
}));

import { useOsNotifyPoller } from "./useOsNotifyPoller";

function event(id: string, sourceType: string): InboxEvent {
  return {
    id,
    agent_id: "default",
    source_type: sourceType,
    source_id: "source",
    event_type: "test",
    status: "success",
    severity: "info",
    title: id,
    body: id,
    read: false,
    created_at: 1,
  };
}

describe("useOsNotifyPoller", () => {
  beforeEach(() => {
    mockGetInboxEvents.mockReset();
    mockGetPushMessages.mockReset();
    mockGetPushMessages.mockResolvedValue({ pending_approvals: [] });
    mockGetInboxEvents.mockResolvedValue({ events: [] });
    useOsNotify.setState({
      history: [],
      toasts: [],
      approvalCount: 0,
      inboxCount: 0,
      centerOpen: false,
      seeded: false,
      knownIds: new Set<string>(),
      communityScope: undefined,
    });
  });

  it("uses the Inbox query limit and source filter for unread counts", async () => {
    mockGetInboxEvents.mockResolvedValue({
      unread_count: 12,
      events: [
        event("cron", "cron"),
        event("heartbeat", "heartbeat"),
        event("memory", "memory"),
        event("skill", "skill_autoupdate"),
        event("approval", "approval"),
        event("manual", "manual"),
      ],
    });

    const { unmount } = renderHook(() => useOsNotifyPoller());

    await waitFor(() => expect(useOsNotify.getState().seeded).toBe(true));
    expect(mockGetInboxEvents).toHaveBeenCalledWith({
      unread_only: true,
      limit: 200,
      source_types: [
        "cron",
        "heartbeat",
        "memory",
        "skill_autoupdate",
        "mail",
        "community",
      ],
      exclude_acl_pending: true,
    });
    expect(useOsNotify.getState().inboxCount).toBe(12);

    unmount();
  });

  it("ignores pre-disconnect responses that arrive after a clear notification", async () => {
    let finish!: (value: unknown) => void;
    mockGetInboxEvents.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const old = {
      id: "ib:community:old",
      kind: "inbox" as const,
      title: "old",
      body: "old account",
      createdAt: 1,
      read: false,
      sourceType: "community",
    };
    useOsNotify.setState({
      seeded: true,
      communityScope: "old-scope",
      history: [old],
      toasts: [old],
      knownIds: new Set([old.id]),
    });
    const { unmount } = renderHook(() => useOsNotifyPoller());
    await waitFor(() => expect(mockGetInboxEvents).toHaveBeenCalledOnce());
    mockGetInboxEvents.mockResolvedValue({
      events: [],
      unread_count: 0,
      community_scope: null,
    });
    act(() =>
      window.dispatchEvent(
        new CustomEvent(INBOX_CHANGED_EVENT, {
          detail: { clearSources: ["community"] },
        }),
      ),
    );
    await waitFor(() =>
      expect(useOsNotify.getState().communityScope).toBeNull(),
    );
    await act(async () =>
      finish({
        events: [event("community:old", "community")],
        unread_count: 1,
        community_scope: "old-scope",
      }),
    );
    expect(useOsNotify.getState().history).toEqual([]);
    expect(useOsNotify.getState().toasts).toEqual([]);
    expect(useOsNotify.getState().communityScope).toBeNull();
    unmount();
  });

  it("detects an account switch without the Settings page being mounted", async () => {
    const old = {
      id: "ib:community:old",
      kind: "inbox" as const,
      title: "old",
      body: "old account",
      createdAt: 1,
      read: false,
      sourceType: "community",
    };
    useOsNotify.setState({
      seeded: true,
      communityScope: "old-scope",
      history: [old],
      toasts: [old],
      knownIds: new Set([old.id]),
    });
    mockGetInboxEvents.mockResolvedValue({
      events: [event("community:new", "community")],
      unread_count: 1,
      community_scope: "new-scope",
    });
    const { unmount } = renderHook(() => useOsNotifyPoller());
    await waitFor(() =>
      expect(useOsNotify.getState().communityScope).toBe("new-scope"),
    );
    expect(useOsNotify.getState().history).toEqual([]);
    expect(useOsNotify.getState().toasts).toEqual([]);
    expect(useOsNotify.getState().knownIds.has("ib:community:new")).toBe(true);
    unmount();
  });
});
