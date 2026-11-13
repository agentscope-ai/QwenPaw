import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { startVisiblePolling } from "@/lib/visiblePolling";

const setHidden = (hidden: boolean) => {
  Object.defineProperty(document, "hidden", {
    configurable: true,
    get: () => hidden,
  });
};

describe("startVisiblePolling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    setHidden(false);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("re-reads a function interval before every wait", () => {
    // The measured case this exists for: an idle Project page kept asking
    // every 1.5 s forever, and every answer costs the backend a Project read
    // plus a Task scan.
    const ticks = vi.fn();
    let active = true;
    const stop = startVisiblePolling(ticks, () => (active ? 1_000 : 10_000));

    vi.advanceTimersByTime(1_000);
    expect(ticks).toHaveBeenCalledTimes(1);

    // The interval is re-read when the next wait is scheduled, so a change
    // takes effect from the following tick rather than the pending one.
    active = false;
    vi.advanceTimersByTime(1_000);
    expect(ticks).toHaveBeenCalledTimes(2);
    vi.advanceTimersByTime(8_000);
    expect(ticks).toHaveBeenCalledTimes(2); // idle: nothing for another 9 s
    vi.advanceTimersByTime(2_000);
    expect(ticks).toHaveBeenCalledTimes(3);

    active = true;
    vi.advanceTimersByTime(10_000);
    expect(ticks).toHaveBeenCalledTimes(4); // activity restores the fast tick

    stop();
  });

  it("never schedules faster than the floor", () => {
    const ticks = vi.fn();
    const stop = startVisiblePolling(ticks, () => 1);

    vi.advanceTimersByTime(200);
    expect(ticks).not.toHaveBeenCalled();
    vi.advanceTimersByTime(100);
    expect(ticks).toHaveBeenCalledTimes(1);

    stop();
  });

  it("stops scheduling once disposed", () => {
    const ticks = vi.fn();
    const stop = startVisiblePolling(ticks, 1_000);
    stop();

    vi.advanceTimersByTime(10_000);
    expect(ticks).not.toHaveBeenCalled();
  });

  it("ticks immediately when the tab becomes visible again", () => {
    const ticks = vi.fn();
    const stop = startVisiblePolling(ticks, 5_000);
    ticks.mockClear();

    setHidden(false);
    document.dispatchEvent(new Event("visibilitychange"));
    expect(ticks).toHaveBeenCalledTimes(1);

    // and keeps its own cadence afterwards, without double scheduling
    vi.advanceTimersByTime(5_000);
    expect(ticks).toHaveBeenCalledTimes(2);
    stop();
  });

  it("skips ticks while the tab is hidden", () => {
    const ticks = vi.fn();
    const stop = startVisiblePolling(ticks, 1_000);
    setHidden(true);
    ticks.mockClear();

    vi.advanceTimersByTime(5_000);
    expect(ticks).not.toHaveBeenCalled();

    setHidden(false);
    document.dispatchEvent(new Event("visibilitychange"));
    expect(ticks).toHaveBeenCalledTimes(1);
    stop();
  });
});
