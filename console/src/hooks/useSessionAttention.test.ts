import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  hasUnseenCompletion,
  sessionAttentionKey,
  useSessionAttentionStore,
  type AttentionSession,
} from "../stores/sessionAttentionStore";
import { useSessionAttention } from "./useSessionAttention";

const T0 = "2026-09-16T10:00:00.000Z";
const T1 = "2026-09-16T11:00:00.000Z";

function resetStore() {
  useSessionAttentionStore.setState({ seenFinishedAt: {} });
}

function setVisible(visible: boolean) {
  Object.defineProperty(document, "visibilityState", {
    value: visible ? "visible" : "hidden",
    configurable: true,
    writable: true,
  });
}

beforeEach(() => {
  resetStore();
  setVisible(true);
});

describe("sessionAttentionKey", () => {
  it("prefers the real id when present", () => {
    expect(sessionAttentionKey("a1", { id: "local", realId: "real" })).toBe(
      "a1:real",
    );
  });

  it("falls back to the local id", () => {
    expect(sessionAttentionKey("a1", { id: "local" })).toBe("a1:local");
  });

  it("falls back when the real id is an empty string", () => {
    expect(sessionAttentionKey("a1", { id: "local", realId: "" })).toBe(
      "a1:local",
    );
  });
});

describe("hasUnseenCompletion", () => {
  it("is false when the session never finished", () => {
    expect(hasUnseenCompletion({ "a1:s1": T1 }, "a1", { id: "s1" })).toBe(
      false,
    );
    expect(
      hasUnseenCompletion({ "a1:s1": T1 }, "a1", {
        id: "s1",
        lastFinishedAt: null,
      }),
    ).toBe(false);
  });

  it("is false when the key was never initialised", () => {
    expect(
      hasUnseenCompletion({}, "a1", { id: "s1", lastFinishedAt: T1 }),
    ).toBe(false);
  });

  it("is true when the key exists but nothing was seen yet", () => {
    expect(
      hasUnseenCompletion({ "a1:s1": null }, "a1", {
        id: "s1",
        lastFinishedAt: T1,
      }),
    ).toBe(true);
  });

  it("is true when the completion is newer than what was seen", () => {
    expect(
      hasUnseenCompletion({ "a1:s1": T0 }, "a1", {
        id: "s1",
        lastFinishedAt: T1,
      }),
    ).toBe(true);
  });

  it("is false when the completion was already seen", () => {
    expect(
      hasUnseenCompletion({ "a1:s1": T1 }, "a1", {
        id: "s1",
        lastFinishedAt: T1,
      }),
    ).toBe(false);
  });

  it("is false when the completion is older than what was seen", () => {
    expect(
      hasUnseenCompletion({ "a1:s1": T1 }, "a1", {
        id: "s1",
        lastFinishedAt: T0,
      }),
    ).toBe(false);
  });

  it("is false when either timestamp fails to parse", () => {
    expect(
      hasUnseenCompletion({ "a1:s1": "not a date" }, "a1", {
        id: "s1",
        lastFinishedAt: T1,
      }),
    ).toBe(false);
    expect(
      hasUnseenCompletion({ "a1:s1": T0 }, "a1", {
        id: "s1",
        lastFinishedAt: "not a date",
      }),
    ).toBe(false);
  });

  it("keys by real id so a local alias does not create a second entry", () => {
    expect(
      hasUnseenCompletion({ "a1:real": T0 }, "a1", {
        id: "local",
        realId: "real",
        lastFinishedAt: T1,
      }),
    ).toBe(true);
  });

  it("separates two agents with the same session id", () => {
    const seen = { "a1:s1": T1 };
    expect(
      hasUnseenCompletion(seen, "a1", { id: "s1", lastFinishedAt: T1 }),
    ).toBe(false);
    // a2 has no entry at all, so it is not unseen either (never initialised)
    expect(
      hasUnseenCompletion(seen, "a2", { id: "s1", lastFinishedAt: T1 }),
    ).toBe(false);
  });
});

describe("useSessionAttention unseen set", () => {
  const sessions: AttentionSession[] = [
    { id: "s1", lastFinishedAt: T1 },
    { id: "s2", lastFinishedAt: T0 },
    { id: "s3" },
  ];

  it("initialises the store from the sessions it is given", () => {
    renderHook(() => useSessionAttention("a1", sessions, undefined));
    const seen = useSessionAttentionStore.getState().seenFinishedAt;
    // Existing completions become the baseline so an upgrade does not mark
    // every past completion unread.
    expect(seen).toEqual({ "a1:s1": T1, "a1:s2": T0, "a1:s3": null });
  });

  it("reports nothing unseen right after initialising", () => {
    const { result } = renderHook(() =>
      useSessionAttention("a1", sessions, undefined),
    );
    expect(result.current.size).toBe(0);
  });

  it("flags a session that completes again after being initialised", () => {
    const { result, rerender } = renderHook(
      ({ list }: { list: AttentionSession[] }) =>
        useSessionAttention("a1", list, undefined),
      { initialProps: { list: sessions } },
    );
    rerender({
      list: [
        { id: "s1", lastFinishedAt: "2026-09-16T12:00:00.000Z" },
        sessions[1],
        sessions[2],
      ],
    });
    expect(result.current.has("s1")).toBe(true);
    expect(result.current.size).toBe(1);
  });

  it("never flags the session currently open in a visible tab", () => {
    useSessionAttentionStore.setState({ seenFinishedAt: { "a1:s1": T0 } });
    const { result } = renderHook(() =>
      useSessionAttention("a1", sessions, "s1"),
    );
    expect(result.current.has("s1")).toBe(false);
  });

  it("never shows the open session as unseen on the very first render", () => {
    // The mount effect marks the current session seen, so the FINAL state
    // converges either way. What this pins is the first render frame: without
    // the isVisibleCurrentSession exclusion the session you are already looking
    // at would appear in the unseen set for one frame (a badge flash) before
    // the effect settles. Capturing every render is the only way to observe it.
    useSessionAttentionStore.setState({ seenFinishedAt: { "a1:s1": T0 } });
    const list: AttentionSession[] = [{ id: "s1", lastFinishedAt: T1 }];
    const renders: Array<ReadonlySet<string>> = [];
    renderHook(() => {
      const value = useSessionAttention("a1", list, "s1");
      renders.push(value);
      return value;
    });
    expect(renders.length).toBeGreaterThan(1);
    expect(renders[0].has("s1")).toBe(false);
    expect(renders[renders.length - 1].has("s1")).toBe(false);
  });

  it("flags the current session when the tab is hidden", () => {
    useSessionAttentionStore.setState({ seenFinishedAt: { "a1:s1": T0 } });
    setVisible(false);
    const { result } = renderHook(() =>
      useSessionAttention("a1", sessions, "s1"),
    );
    expect(result.current.has("s1")).toBe(true);
  });

  it("matches the current session by real id too", () => {
    useSessionAttentionStore.setState({
      seenFinishedAt: { "a1:real1": T0 },
    });
    const list: AttentionSession[] = [
      { id: "local1", realId: "real1", lastFinishedAt: T1 },
    ];
    const { result } = renderHook(() =>
      useSessionAttention("a1", list, "real1"),
    );
    expect(result.current.has("local1")).toBe(false);
  });

  it("does not run markSeen while the tab is hidden, leaving the seen value stale", () => {
    // Seed an OLD seen value. initializeSessions will NOT overwrite an existing
    // key, and markSeen is gated on visibility, so while hidden the value must
    // stay at the stale T0 rather than advancing to the session's T1.
    useSessionAttentionStore.setState({ seenFinishedAt: { "a1:s1": T0 } });
    setVisible(false);
    const list: AttentionSession[] = [{ id: "s1", lastFinishedAt: T1 }];
    renderHook(() => useSessionAttention("a1", list, "s1"));
    expect(useSessionAttentionStore.getState().seenFinishedAt["a1:s1"]).toBe(
      T0,
    );
  });

  it("initialises an unknown session to its own completion as the baseline", () => {
    // A session never seen before is baselined at its lastFinishedAt, so a
    // feature upgrade does not mark all past completions unread.
    setVisible(false);
    const list: AttentionSession[] = [{ id: "s9", lastFinishedAt: T1 }];
    renderHook(() => useSessionAttention("a1", list, undefined));
    expect(useSessionAttentionStore.getState().seenFinishedAt["a1:s9"]).toBe(
      T1,
    );
  });

  it("marks the current session seen on mount when the tab is visible", () => {
    useSessionAttentionStore.setState({ seenFinishedAt: { "a1:s1": T0 } });
    const list: AttentionSession[] = [{ id: "s1", lastFinishedAt: T1 }];
    renderHook(() => useSessionAttention("a1", list, "s1"));
    expect(useSessionAttentionStore.getState().seenFinishedAt["a1:s1"]).toBe(
      T1,
    );
  });

  it("marks the current session seen when the tab becomes visible", () => {
    useSessionAttentionStore.setState({ seenFinishedAt: { "a1:s1": T0 } });
    setVisible(false);
    const list: AttentionSession[] = [{ id: "s1", lastFinishedAt: T1 }];
    renderHook(() => useSessionAttention("a1", list, "s1"));
    expect(useSessionAttentionStore.getState().seenFinishedAt["a1:s1"]).toBe(
      T0,
    );
    setVisible(true);
    document.dispatchEvent(new Event("visibilitychange"));
    expect(useSessionAttentionStore.getState().seenFinishedAt["a1:s1"]).toBe(
      T1,
    );
  });

  it("does nothing on visibilitychange when no session is current", () => {
    const list: AttentionSession[] = [{ id: "s1", lastFinishedAt: T1 }];
    renderHook(() => useSessionAttention("a1", list, undefined));
    const before = useSessionAttentionStore.getState().seenFinishedAt;
    document.dispatchEvent(new Event("visibilitychange"));
    expect(useSessionAttentionStore.getState().seenFinishedAt).toEqual(before);
  });

  it("ignores a current session id that is not in the list", () => {
    const list: AttentionSession[] = [{ id: "s1", lastFinishedAt: T1 }];
    renderHook(() => useSessionAttention("a1", list, "missing"));
    expect(
      useSessionAttentionStore.getState().seenFinishedAt["a1:missing"],
    ).toBeUndefined();
  });

  it("removes the visibilitychange listener on unmount", () => {
    const removeSpy = vi.spyOn(document, "removeEventListener");
    const list: AttentionSession[] = [{ id: "s1", lastFinishedAt: T1 }];
    const { unmount } = renderHook(() => useSessionAttention("a1", list, "s1"));
    unmount();
    expect(removeSpy).toHaveBeenCalledWith(
      "visibilitychange",
      expect.any(Function),
    );
    removeSpy.mockRestore();
  });

  it("returns an empty set for an empty session list", () => {
    const { result } = renderHook(() =>
      useSessionAttention("a1", [], undefined),
    );
    expect(result.current.size).toBe(0);
  });
});

describe("useSessionAttentionStore actions", () => {
  it("does not rewrite an entry it already knows", () => {
    useSessionAttentionStore.setState({ seenFinishedAt: { "a1:s1": T0 } });
    useSessionAttentionStore
      .getState()
      .initializeSessions("a1", [{ id: "s1", lastFinishedAt: T1 }]);
    // The baseline is only set on first sight, so T0 is preserved.
    expect(useSessionAttentionStore.getState().seenFinishedAt["a1:s1"]).toBe(
      T0,
    );
  });

  it("keeps the same state object when nothing needs initialising", () => {
    useSessionAttentionStore.setState({ seenFinishedAt: { "a1:s1": T0 } });
    const before = useSessionAttentionStore.getState();
    before.initializeSessions("a1", [{ id: "s1", lastFinishedAt: T0 }]);
    expect(useSessionAttentionStore.getState()).toBe(before);
  });

  it("markSeen ignores a session that never finished", () => {
    useSessionAttentionStore.getState().markSeen("a1", { id: "s1" });
    expect(
      useSessionAttentionStore.getState().seenFinishedAt["a1:s1"],
    ).toBeUndefined();
  });

  it("markSeen keeps an existing seen value for a session that never finished", () => {
    // Without the `!lastFinishedAt` early return this would overwrite the
    // stored T0 with null (undefined ?? null). Seeding a previous value is what
    // makes the guard observable - on an empty store both paths are identical.
    useSessionAttentionStore.setState({ seenFinishedAt: { "a1:s1": T0 } });
    useSessionAttentionStore.getState().markSeen("a1", { id: "s1" });
    expect(useSessionAttentionStore.getState().seenFinishedAt["a1:s1"]).toBe(
      T0,
    );
  });

  it("markSeen does not rewrite an identical timestamp", () => {
    useSessionAttentionStore.setState({ seenFinishedAt: { "a1:s1": T1 } });
    const before = useSessionAttentionStore.getState();
    before.markSeen("a1", { id: "s1", lastFinishedAt: T1 });
    expect(useSessionAttentionStore.getState()).toBe(before);
  });

  it("markSeen records a newer completion", () => {
    useSessionAttentionStore.setState({ seenFinishedAt: { "a1:s1": T0 } });
    useSessionAttentionStore
      .getState()
      .markSeen("a1", { id: "s1", lastFinishedAt: T1 });
    expect(useSessionAttentionStore.getState().seenFinishedAt["a1:s1"]).toBe(
      T1,
    );
  });
});
