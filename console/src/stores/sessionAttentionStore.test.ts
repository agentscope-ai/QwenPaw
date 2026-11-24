import { beforeEach, describe, expect, it } from "vitest";
import {
  hasUnseenCompletion,
  sessionAttentionKey,
  useSessionAttentionStore,
} from "./sessionAttentionStore";

const session = {
  id: "local-id",
  realId: "chat-1",
  lastFinishedAt: "2026-08-25T08:00:00.000Z",
};

describe("sessionAttentionStore", () => {
  beforeEach(() => {
    localStorage.clear();
    useSessionAttentionStore.setState({ seenFinishedAt: {} });
  });

  it("uses the backend id so local id remapping keeps the read marker", () => {
    expect(sessionAttentionKey("agent-a", session)).toBe("agent-a:chat-1");
  });

  it("baselines existing completions without marking old history unseen", () => {
    useSessionAttentionStore
      .getState()
      .initializeSessions("agent-a", [session]);

    expect(
      hasUnseenCompletion(
        useSessionAttentionStore.getState().seenFinishedAt,
        "agent-a",
        session,
      ),
    ).toBe(false);
  });

  it("marks a newer completion unseen until the session is viewed", () => {
    const store = useSessionAttentionStore.getState();
    store.initializeSessions("agent-a", [session]);
    const rerun = {
      ...session,
      lastFinishedAt: "2026-08-25T09:00:00.000Z",
    };

    expect(
      hasUnseenCompletion(
        useSessionAttentionStore.getState().seenFinishedAt,
        "agent-a",
        rerun,
      ),
    ).toBe(true);

    useSessionAttentionStore.getState().markSeen("agent-a", rerun);
    expect(
      hasUnseenCompletion(
        useSessionAttentionStore.getState().seenFinishedAt,
        "agent-a",
        rerun,
      ),
    ).toBe(false);
  });

  it("keeps read markers separate for each agent", () => {
    useSessionAttentionStore
      .getState()
      .initializeSessions("agent-a", [session]);

    expect(
      hasUnseenCompletion(
        useSessionAttentionStore.getState().seenFinishedAt,
        "agent-b",
        session,
      ),
    ).toBe(false);
  });

  it("ignores invalid completion timestamps without poisoning the baseline", () => {
    const invalid = { ...session, lastFinishedAt: "not-a-date" };
    const store = useSessionAttentionStore.getState();
    store.initializeSessions("agent-a", [invalid]);
    expect(
      hasUnseenCompletion(
        useSessionAttentionStore.getState().seenFinishedAt,
        "agent-a",
        invalid,
      ),
    ).toBe(false);
    expect(
      hasUnseenCompletion(
        useSessionAttentionStore.getState().seenFinishedAt,
        "agent-a",
        session,
      ),
    ).toBe(true);
    store.markSeen("agent-a", invalid);
    expect(
      useSessionAttentionStore.getState().seenFinishedAt["agent-a:chat-1"],
    ).toBeNull();
  });

  it("does not move a read marker backwards after a stale refresh", () => {
    const store = useSessionAttentionStore.getState();
    const newer = { ...session, lastFinishedAt: "2026-08-25T09:00:00Z" };
    store.markSeen("agent-a", newer);
    store.markSeen("agent-a", session);
    expect(
      hasUnseenCompletion(
        useSessionAttentionStore.getState().seenFinishedAt,
        "agent-a",
        newer,
      ),
    ).toBe(false);
  });
});
