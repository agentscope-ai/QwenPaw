import { beforeEach, describe, expect, it } from "vitest";
import {
  clearBackgroundAbortIfCurrent,
  getBackgroundAbort,
  hasBackgroundQueue,
  resetBackgroundQueueRegistryForTests,
  setBackgroundAbort,
  stopBackgroundQueue,
} from "./backgroundQueueRegistry";

// ---------------------------------------------------------------------------
// Background queue abort registry — regression for #505 and #424
//
// The background sender keeps draining the message queue after the Chat page
// unmounts, one AbortController per session.
//
// - #505: after a stop, the state must be FULLY reset: the controller is
//   aborted AND removed from the registry, so a subsequent send starts a
//   fresh sender instead of reusing the stale aborted one (the old symptom
//   was "Answer has been stopped" until a page refresh).
// - #424: a switch/stop must actually abort the running sender — the signal
//   handed to fetch is only useful if stop() aborts its controller.
// ---------------------------------------------------------------------------
describe("background queue registry (#505 / #424)", () => {
  beforeEach(() => {
    resetBackgroundQueueRegistryForTests();
  });

  it("registers and retrieves a sender controller per session", () => {
    const ctrl = new AbortController();
    setBackgroundAbort("session-a", ctrl);

    expect(getBackgroundAbort("session-a")).toBe(ctrl);
    expect(hasBackgroundQueue("session-a")).toBe(true);
    expect(hasBackgroundQueue("session-b")).toBe(false);
  });

  it("stop aborts the controller AND removes it (state fully reset, #505)", () => {
    const ctrl = new AbortController();
    setBackgroundAbort("session-a", ctrl);

    stopBackgroundQueue("session-a");

    // The signal fired for the running sender...
    expect(ctrl.signal.aborted).toBe(true);
    // ...and the registry no longer holds it: a new send starts fresh.
    expect(getBackgroundAbort("session-a")).toBeUndefined();
    expect(hasBackgroundQueue("session-a")).toBe(false);
  });

  it("stop is idempotent for a session without a sender", () => {
    expect(() => stopBackgroundQueue("ghost")).not.toThrow();
  });

  it("stop for one session leaves other sessions running", () => {
    const ctrlA = new AbortController();
    const ctrlB = new AbortController();
    setBackgroundAbort("session-a", ctrlA);
    setBackgroundAbort("session-b", ctrlB);

    stopBackgroundQueue("session-a");

    expect(ctrlA.signal.aborted).toBe(true);
    expect(ctrlB.signal.aborted).toBe(false);
    expect(hasBackgroundQueue("session-b")).toBe(true);
  });

  it("stop without a key aborts and clears every sender", () => {
    const ctrlA = new AbortController();
    const ctrlB = new AbortController();
    setBackgroundAbort("session-a", ctrlA);
    setBackgroundAbort("session-b", ctrlB);

    stopBackgroundQueue();

    expect(ctrlA.signal.aborted).toBe(true);
    expect(ctrlB.signal.aborted).toBe(true);
    expect(hasBackgroundQueue("session-a")).toBe(false);
    expect(hasBackgroundQueue("session-b")).toBe(false);
  });

  it("replacing a sender aborts nothing (startBackgroundQueue stops the old one first)", () => {
    const old = new AbortController();
    setBackgroundAbort("session-a", old);
    const fresh = new AbortController();
    setBackgroundAbort("session-a", fresh);

    expect(getBackgroundAbort("session-a")).toBe(fresh);
    expect(old.signal.aborted).toBe(false);
  });

  it("clearBackgroundAbortIfCurrent removes only the matching controller", () => {
    const ctrl = new AbortController();
    setBackgroundAbort("session-a", ctrl);

    clearBackgroundAbortIfCurrent("session-a", new AbortController());
    expect(hasBackgroundQueue("session-a")).toBe(true);

    clearBackgroundAbortIfCurrent("session-a", ctrl);
    expect(hasBackgroundQueue("session-a")).toBe(false);
  });

  it("stop → re-register works (the #505 recovery path)", () => {
    const first = new AbortController();
    setBackgroundAbort("session-a", first);
    stopBackgroundQueue("session-a");

    // A fresh send after stopping must get a usable, non-aborted signal.
    const second = new AbortController();
    setBackgroundAbort("session-a", second);

    expect(second.signal.aborted).toBe(false);
    expect(getBackgroundAbort("session-a")).toBe(second);
  });
});
