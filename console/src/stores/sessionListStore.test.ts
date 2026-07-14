import { describe, it, expect, beforeEach, vi } from "vitest";
import {
  useSessionListStore,
  syncSessionsGlobal,
  type ExtendedSession,
} from "./sessionListStore";

function makeSession(
  id: string,
  extra: Partial<ExtendedSession> = {},
): ExtendedSession {
  return {
    id,
    title: `title-${id}`,
    ...extra,
  } as ExtendedSession;
}

describe("sessionListStore", () => {
  beforeEach(() => {
    useSessionListStore.setState({
      sessions: [],
      lastUpdated: 0,
      _setLibrarySessions: null,
    });
  });

  // ---------------------------------------------------------------------------
  // Initial state
  // ---------------------------------------------------------------------------

  it("starts with an empty session list and lastUpdated 0", () => {
    const state = useSessionListStore.getState();
    expect(state.sessions).toEqual([]);
    expect(state.lastUpdated).toBe(0);
    expect(state._setLibrarySessions).toBeNull();
  });

  // ---------------------------------------------------------------------------
  // syncFromLibrary
  // ---------------------------------------------------------------------------

  it("syncFromLibrary stores sessions and the library setter", () => {
    const sessions = [makeSession("a"), makeSession("b")];
    const setLibrary = vi.fn();

    useSessionListStore.getState().syncFromLibrary(sessions, setLibrary);

    const state = useSessionListStore.getState();
    expect(state.sessions).toEqual(sessions);
    expect(state._setLibrarySessions).toBe(setLibrary);
    expect(state.lastUpdated).toBeGreaterThan(0);
  });

  it("syncFromLibrary updates lastUpdated on each call", () => {
    useSessionListStore.getState().syncFromLibrary([], vi.fn());
    const first = useSessionListStore.getState().lastUpdated;

    // Date.now() granularity can be ms; ensure a later timestamp.
    const orig = Date.now;
    Date.now = () => first + 5;
    try {
      useSessionListStore.getState().syncFromLibrary([], vi.fn());
    } finally {
      Date.now = orig;
    }

    expect(useSessionListStore.getState().lastUpdated).toBe(first + 5);
  });

  // ---------------------------------------------------------------------------
  // syncSessions — propagates to the library if registered
  // ---------------------------------------------------------------------------

  it("syncSessions updates the store even when no library setter is registered", () => {
    const sessions = [makeSession("a")];

    useSessionListStore.getState().syncSessions(sessions);

    const state = useSessionListStore.getState();
    expect(state.sessions).toEqual(sessions);
    expect(state.lastUpdated).toBeGreaterThan(0);
  });

  it("syncSessions propagates the new sessions to the registered library setter", () => {
    const setLibrary = vi.fn();
    useSessionListStore
      .getState()
      .syncFromLibrary([makeSession("old")], setLibrary);

    const next = [makeSession("new1"), makeSession("new2")];
    useSessionListStore.getState().syncSessions(next);

    expect(setLibrary).toHaveBeenCalledWith(next);
    expect(useSessionListStore.getState().sessions).toEqual(next);
  });

  it("syncSessions does not throw when _setLibrarySessions is null", () => {
    expect(() =>
      useSessionListStore.getState().syncSessions([makeSession("a")]),
    ).not.toThrow();
  });

  // ---------------------------------------------------------------------------
  // syncSessionsGlobal
  // ---------------------------------------------------------------------------

  it("syncSessionsGlobal delegates to the store's syncSessions", () => {
    const setLibrary = vi.fn();
    useSessionListStore.getState().syncFromLibrary([], setLibrary);

    const sessions = [makeSession("g1")];
    syncSessionsGlobal(sessions);

    expect(useSessionListStore.getState().sessions).toEqual(sessions);
    expect(setLibrary).toHaveBeenCalledWith(sessions);
  });

  // ---------------------------------------------------------------------------
  // Re-registering the library setter
  // ---------------------------------------------------------------------------

  it("calling syncFromLibrary again replaces the previous library setter", () => {
    const first = vi.fn();
    const second = vi.fn();
    useSessionListStore.getState().syncFromLibrary([], first);
    useSessionListStore.getState().syncFromLibrary([], second);

    useSessionListStore.getState().syncSessions([makeSession("x")]);

    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledWith([expect.objectContaining({ id: "x" })]);
  });
});
