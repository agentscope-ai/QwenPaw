/**
 * What this file pins for `stoppedTurns`:
 *
 * The module header (:1-19) states the contract this suite enforces: a stop
 * click is the only reliable fact left when the SSE stream already died, so
 * the recorded id must be the BACKEND-resolved one, and an id that cannot be
 * resolved must never be stored at all (a flag that matches no session would
 * later mislabel a healthy turn's tool calls as interrupted).
 *
 * Real consumers: `turnEndedProvider.tsx:26` (reads the store) and
 * `Chat/index.tsx:86` (calls mark/clear). Their suites cover the wiring, not
 * these guards, which is why the four early-return branches at :38/:42/:44
 * and :53/:55/:57 are the target here.
 *
 * Mock shape follows the sibling precedent
 * `src/pages/Chat/turnEndedProvider.test.tsx:6-9` (mock the resolver), and
 * the store-reset shape follows `src/stores/backgroundTasksStore.test.ts:8`.
 * The resolver is a `vi.hoisted` instance so each case can decide what an id
 * resolves to, including "resolves to nothing".
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const h = vi.hoisted(() => {
  const resolve = vi.fn();
  return { resolve };
});

vi.mock("../../utils/resolveBackendSessionId", () => ({
  resolveBackendSessionId: (id?: string | null) => h.resolve(id),
}));

import {
  clearTurnStopped,
  markTurnStopped,
  useStoppedTurnsStore,
} from "./stoppedTurns";

/** Every id maps to itself unless a case says otherwise. */
function identityResolver(): void {
  h.resolve.mockImplementation((id?: string | null) => id ?? "");
}

function storedIds(): string[] {
  return [...useStoppedTurnsStore.getState().stoppedSessionIds].sort();
}

beforeEach(() => {
  useStoppedTurnsStore.setState({ stoppedSessionIds: new Set() });
  h.resolve.mockReset();
  identityResolver();
});

describe("markTurnStopped", () => {
  it("stores the backend-resolved id, not the raw one", () => {
    h.resolve.mockImplementation((id?: string | null) =>
      id === "local-1791200000" ? "backend-session-7" : id ?? "",
    );

    markTurnStopped("local-1791200000");

    expect(storedIds()).toEqual(["backend-session-7"]);
    expect(h.resolve).toHaveBeenCalledWith("local-1791200000");
  });

  it("stores nothing when no id was passed at all", () => {
    markTurnStopped(undefined);
    expect(storedIds()).toEqual([]);

    markTurnStopped(null);
    expect(storedIds()).toEqual([]);

    markTurnStopped("");
    expect(storedIds()).toEqual([]);
    // The resolver must not be consulted for an absent id.
    expect(h.resolve).not.toHaveBeenCalled();
  });

  it("stores nothing when the id is only whitespace", () => {
    markTurnStopped("   ");

    expect(storedIds()).toEqual([]);
    expect(h.resolve).not.toHaveBeenCalled();
  });

  it("trims the id before resolving it", () => {
    markTurnStopped("  session-a  ");

    expect(h.resolve).toHaveBeenCalledWith("session-a");
    expect(storedIds()).toEqual(["session-a"]);
  });

  it("stores nothing when the resolver cannot map the id", () => {
    // :42 guard - an unresolved id must not become a flag that matches
    // no session at all.
    h.resolve.mockReturnValue("");

    markTurnStopped("unresolvable-1");

    expect(storedIds()).toEqual([]);
    expect(useStoppedTurnsStore.getState().stoppedSessionIds.size).toBe(0);
  });

  it("keeps one entry when the same session is stopped twice", () => {
    markTurnStopped("session-a");
    const afterFirst = useStoppedTurnsStore.getState().stoppedSessionIds;

    markTurnStopped("session-a");
    const afterSecond = useStoppedTurnsStore.getState().stoppedSessionIds;

    expect(storedIds()).toEqual(["session-a"]);
    // :44 guard returns before setState, so the instance is untouched.
    expect(afterSecond).toBe(afterFirst);
  });

  it("keeps distinct sessions side by side", () => {
    markTurnStopped("session-a");
    markTurnStopped("session-b");

    expect(storedIds()).toEqual(["session-a", "session-b"]);
  });

  it("publishes a new Set instance so subscribers re-render", () => {
    const before = useStoppedTurnsStore.getState().stoppedSessionIds;

    markTurnStopped("session-a");
    const after = useStoppedTurnsStore.getState().stoppedSessionIds;

    expect(after).not.toBe(before);
    // The previous snapshot must not have been mutated in place.
    expect(before.size).toBe(0);
    expect(after.has("session-a")).toBe(true);
  });
});

describe("clearTurnStopped", () => {
  it("drops exactly the session whose turn restarted", () => {
    markTurnStopped("session-a");
    markTurnStopped("session-b");

    clearTurnStopped("session-a");

    expect(storedIds()).toEqual(["session-b"]);
  });

  it("does nothing when called with an empty id", () => {
    markTurnStopped("session-a");
    // The arrange call above legitimately consulted the resolver once, so
    // drop the call record (mockClear keeps the identity implementation set
    // in beforeEach) to assert that THIS call does not reach it.
    h.resolve.mockClear();
    const before = useStoppedTurnsStore.getState().stoppedSessionIds;

    clearTurnStopped("");

    expect(storedIds()).toEqual(["session-a"]);
    expect(useStoppedTurnsStore.getState().stoppedSessionIds).toBe(before);
    expect(h.resolve).not.toHaveBeenCalled();
  });

  it("does nothing when called with a whitespace-only id", () => {
    markTurnStopped("session-a");
    h.resolve.mockClear();

    clearTurnStopped("   ");

    expect(storedIds()).toEqual(["session-a"]);
    expect(h.resolve).not.toHaveBeenCalled();
  });

  it("does nothing when the resolver cannot map the id", () => {
    // :55 guard - clearing by an unresolved id must not clear anything.
    markTurnStopped("session-a");
    h.resolve.mockImplementation((id?: string | null) =>
      id === "session-a" ? "session-a" : "",
    );

    clearTurnStopped("unresolvable-2");

    expect(storedIds()).toEqual(["session-a"]);
  });

  it("does nothing for a session that was never stopped", () => {
    markTurnStopped("session-a");
    const before = useStoppedTurnsStore.getState().stoppedSessionIds;

    clearTurnStopped("session-z");

    expect(storedIds()).toEqual(["session-a"]);
    // :57 guard returns the existing instance rather than a fresh copy.
    expect(useStoppedTurnsStore.getState().stoppedSessionIds).toBe(before);
  });

  it("trims the id before resolving it", () => {
    markTurnStopped("session-a");

    clearTurnStopped("  session-a  ");

    expect(h.resolve).toHaveBeenCalledWith("session-a");
    expect(storedIds()).toEqual([]);
  });

  it("lets a stopped session be stopped again after it was cleared", () => {
    markTurnStopped("session-a");
    clearTurnStopped("session-a");
    expect(storedIds()).toEqual([]);

    markTurnStopped("session-a");

    expect(storedIds()).toEqual(["session-a"]);
  });
});

describe("store shape", () => {
  it("exposes the stopped id set as its only state member", () => {
    const state = useStoppedTurnsStore.getState();

    expect(Object.keys(state)).toEqual(["stoppedSessionIds"]);
    expect(state.stoppedSessionIds instanceof Set).toBe(true);
  });
});
