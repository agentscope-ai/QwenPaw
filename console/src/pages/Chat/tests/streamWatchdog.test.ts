/**
 * Tests for the stream-death watchdog.
 *
 * Covers the state machine: a believed-running turn with no active
 * stream recovers via handleReconnect while the backend still
 * generates; a finished backend stops after limited finalize attempts;
 * active streams, the post-send quiet window and the cooldown suppress
 * action.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createStreamWatchdog, type StreamWatchdog } from "../streamWatchdog";

function setup(
  overrides: Partial<Parameters<typeof createStreamWatchdog>[0]> = {},
) {
  const state = {
    running: true,
    active: 0,
    generating: true,
    lastSendAt: 0,
  };
  let nowMs = 100_000;
  const reconnect = vi.fn();
  const probe = vi.fn(async () => state.generating);

  const watchdog: StreamWatchdog = createStreamWatchdog({
    isRunningTurn: () => state.running,
    activeStreamCount: () => state.active,
    isSessionGenerating: probe,
    requestReconnect: reconnect,
    lastSendAt: () => state.lastSendAt,
    now: () => nowMs,
    ...overrides,
  });
  return {
    state,
    reconnect,
    probe,
    watchdog,
    advance: (ms: number) => (nowMs += ms),
  };
}

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("createStreamWatchdog", () => {
  it("reconnects when the stream died and the backend still generates", async () => {
    const ctx = setup();
    await ctx.watchdog.tick();

    expect(ctx.probe).toHaveBeenCalledTimes(1);
    expect(ctx.reconnect).toHaveBeenCalledTimes(1);
  });

  it("ignores ticks while a stream is active", async () => {
    const ctx = setup();
    ctx.state.active = 1;
    await ctx.watchdog.tick();

    expect(ctx.probe).not.toHaveBeenCalled();
    expect(ctx.reconnect).not.toHaveBeenCalled();
  });

  it("respects the post-send quiet window", async () => {
    const ctx = setup();
    ctx.state.lastSendAt = 95_000; // 5s before now
    await ctx.watchdog.tick();

    expect(ctx.reconnect).not.toHaveBeenCalled();
  });

  it("obeys the reconnect cooldown", async () => {
    const ctx = setup();
    await ctx.watchdog.tick(); // reconnect #1
    ctx.advance(2_000); // inside the 8s cooldown
    await ctx.watchdog.tick();

    expect(ctx.reconnect).toHaveBeenCalledTimes(1);
    ctx.advance(10_000);
    await ctx.watchdog.tick();
    expect(ctx.reconnect).toHaveBeenCalledTimes(2);
  });

  it("stops after limited finalize attempts once the backend finished", async () => {
    const ctx = setup();
    ctx.state.generating = false;

    for (let i = 0; i < 6; i += 1) {
      ctx.advance(10_000);
      await ctx.watchdog.tick();
    }
    // one finalize attempt per cooldown window, capped at two
    expect(ctx.reconnect).toHaveBeenCalledTimes(2);
  });

  it("does nothing when no turn is believed running", async () => {
    const ctx = setup();
    ctx.state.running = false;
    await ctx.watchdog.tick();

    expect(ctx.probe).not.toHaveBeenCalled();
  });

  it("reset() re-arms the finalize budget for a new send", async () => {
    const ctx = setup();
    ctx.state.generating = false;
    for (let i = 0; i < 4; i += 1) {
      ctx.advance(10_000);
      await ctx.watchdog.tick();
    }
    expect(ctx.reconnect).toHaveBeenCalledTimes(2);

    ctx.watchdog.reset();
    ctx.advance(10_000);
    await ctx.watchdog.tick();
    expect(ctx.reconnect).toHaveBeenCalledTimes(3);
  });
});
