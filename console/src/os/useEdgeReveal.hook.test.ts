// @vitest-environment jsdom
// Hook-level tests for useEdgeReveal.
//
// Scope note: the sibling useEdgeReveal.test.ts covers the two exported pure
// helpers (resolveEdges / shouldRevealDock) only, so the hook body itself -
// the rAF-throttled global pointermove listener and its hysteresis wiring -
// stays at zero coverage there. This file adds it as a separate module test
// file and does not touch the existing one.
//
// Environment facts these tests rely on (probed locally, not assumed):
//   - vi.useFakeTimers() fakes requestAnimationFrame as well, and
//     advanceTimersByTime(16) runs the queued frame callback.
//   - vi.getTimerCount() reports 0 for a pending animation frame, so it cannot
//     be used to assert "a frame is queued"; the tests assert observable
//     behaviour (how many pointermove events actually change state) instead.
//   - new PointerEvent("pointermove", { clientY }) is available and carries
//     clientY through.
//   - window.innerHeight defaults to 768 in jsdom and is directly assignable.
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useEdgeReveal } from "./useEdgeReveal";

const VIEWPORT = 800;
const FRAME_MS = 16;

function setViewportHeight(height: number) {
  Object.defineProperty(window, "innerHeight", {
    value: height,
    configurable: true,
    writable: true,
  });
}

/** Dispatch a pointermove and let the queued animation frame run. */
function move(y: number) {
  act(() => {
    window.dispatchEvent(new PointerEvent("pointermove", { clientY: y }));
    vi.advanceTimersByTime(FRAME_MS);
  });
}

describe("useEdgeReveal", () => {
  let addSpy: ReturnType<typeof vi.spyOn>;
  let removeSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    vi.useFakeTimers();
    setViewportHeight(VIEWPORT);
    addSpy = vi.spyOn(window, "addEventListener");
    removeSpy = vi.spyOn(window, "removeEventListener");
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    setViewportHeight(768);
  });

  it("starts with both edges cold", () => {
    const { result } = renderHook(() => useEdgeReveal());
    expect(result.current).toEqual({ topHot: false, bottomHot: false });
  });

  it("attaches a global pointermove listener and removes it on unmount", () => {
    const { unmount } = renderHook(() => useEdgeReveal());
    expect(addSpy).toHaveBeenCalledWith("pointermove", expect.any(Function));

    unmount();
    expect(removeSpy).toHaveBeenCalledWith("pointermove", expect.any(Function));
  });

  it("arms the top edge when the pointer reaches the top threshold", () => {
    const { result } = renderHook(() => useEdgeReveal());

    move(0);
    expect(result.current.topHot).toBe(true);
    expect(result.current.bottomHot).toBe(false);
  });

  it("arms the bottom edge when the pointer reaches the bottom threshold", () => {
    const { result } = renderHook(() => useEdgeReveal());

    move(VIEWPORT);
    expect(result.current.bottomHot).toBe(true);
    expect(result.current.topHot).toBe(false);
  });

  it("ignores pointer positions in the middle of the viewport", () => {
    const { result } = renderHook(() => useEdgeReveal());

    move(VIEWPORT / 2);
    expect(result.current).toEqual({ topHot: false, bottomHot: false });
  });

  it("keeps the top edge hot inside the wider reveal band (hysteresis)", () => {
    const { result } = renderHook(() => useEdgeReveal());

    move(0);
    expect(result.current.topHot).toBe(true);

    // Still inside topBand (120) although past threshold (6).
    move(100);
    expect(result.current.topHot).toBe(true);

    // Past the band, the edge is released again.
    move(400);
    expect(result.current.topHot).toBe(false);
  });

  it("keeps the bottom edge hot inside the bottom band (hysteresis)", () => {
    const { result } = renderHook(() => useEdgeReveal());

    move(VIEWPORT);
    expect(result.current.bottomHot).toBe(true);

    // Inside bottomBand (96) although past threshold (6).
    move(VIEWPORT - 50);
    expect(result.current.bottomHot).toBe(true);

    move(VIEWPORT / 2);
    expect(result.current.bottomHot).toBe(false);
  });

  it("reads the live viewport height instead of a captured one", () => {
    const { result } = renderHook(() => useEdgeReveal());

    move(VIEWPORT);
    expect(result.current.bottomHot).toBe(true);

    // Grow the viewport: the same pointer position is no longer at the edge.
    setViewportHeight(2000);
    move(VIEWPORT);
    expect(result.current.bottomHot).toBe(false);

    // Shrink it back: the pointer is at the edge again.
    setViewportHeight(VIEWPORT);
    move(VIEWPORT);
    expect(result.current.bottomHot).toBe(true);
  });

  it("throttles updates through a single animation frame", () => {
    const { result } = renderHook(() => useEdgeReveal());

    // Two moves inside the same frame: only the first schedules work, the
    // second is dropped because a frame is already pending.
    act(() => {
      window.dispatchEvent(new PointerEvent("pointermove", { clientY: 0 }));
      window.dispatchEvent(new PointerEvent("pointermove", { clientY: 400 }));
      vi.advanceTimersByTime(FRAME_MS);
    });

    // The dropped event was the one that would have released the edge, so the
    // first position wins for this frame.
    expect(result.current.topHot).toBe(true);

    // The next frame picks up the current pointer position again.
    move(400);
    expect(result.current.topHot).toBe(false);
  });

  it("does not re-render when the resolved edge state is unchanged", () => {
    const { result } = renderHook(() => useEdgeReveal());

    move(400);
    const first = result.current;

    move(401);
    // Same resolved state, so the hook must hand back the identical object
    // rather than a fresh one (that is what keeps consumers from re-rendering).
    expect(result.current).toBe(first);
    expect(result.current).toEqual({ topHot: false, bottomHot: false });
  });

  it("honours custom threshold and band options", () => {
    const { result } = renderHook(() =>
      useEdgeReveal({ threshold: 20, topBand: 40, bottomBand: 30 }),
    );

    // 15 is past a threshold of 20? No - inside it.
    move(15);
    expect(result.current.topHot).toBe(true);

    // 35 is past the custom topBand of 40? Still inside, so it stays hot.
    move(35);
    expect(result.current.topHot).toBe(true);

    // 45 leaves the custom band.
    move(45);
    expect(result.current.topHot).toBe(false);

    // Bottom band of 30 means only y >= 770 arms it.
    move(VIEWPORT - 40);
    expect(result.current.bottomHot).toBe(false);
    move(VIEWPORT - 20);
    expect(result.current.bottomHot).toBe(true);
  });

  it("re-attaches the listener when the options change", () => {
    const { rerender } = renderHook(
      ({ threshold }) => useEdgeReveal({ threshold }),
      { initialProps: { threshold: 6 } },
    );

    const addCallsBefore = addSpy.mock.calls.filter(
      (c: unknown[]) => c[0] === "pointermove",
    ).length;
    const removeCallsBefore = removeSpy.mock.calls.filter(
      (c: unknown[]) => c[0] === "pointermove",
    ).length;
    expect(addCallsBefore).toBe(1);
    expect(removeCallsBefore).toBe(0);

    rerender({ threshold: 30 });
    const addCallsAfter = addSpy.mock.calls.filter(
      (c: unknown[]) => c[0] === "pointermove",
    ).length;
    const removeCallsAfter = removeSpy.mock.calls.filter(
      (c: unknown[]) => c[0] === "pointermove",
    ).length;
    expect(addCallsAfter).toBe(2);
    expect(removeCallsAfter).toBe(1);
  });

  it("keeps the previous listener when the options are unchanged", () => {
    const { rerender } = renderHook(
      ({ open }) => {
        void open;
        return useEdgeReveal();
      },
      { initialProps: { open: true } },
    );

    rerender({ open: false });
    const addCalls = addSpy.mock.calls.filter(
      (c: unknown[]) => c[0] === "pointermove",
    ).length;
    expect(addCalls).toBe(1);
  });

  it("cancels a pending frame on unmount so no state update leaks", () => {
    const { unmount } = renderHook(() => useEdgeReveal());

    // Queue a frame but unmount before it runs.
    act(() => {
      window.dispatchEvent(new PointerEvent("pointermove", { clientY: 0 }));
    });
    expect(() => unmount()).not.toThrow();

    // Running the frame afterwards must not blow up on an unmounted hook.
    expect(() => {
      act(() => {
        vi.advanceTimersByTime(FRAME_MS);
      });
    }).not.toThrow();
  });

  it("defaults every option when called with no arguments", () => {
    const { result } = renderHook(() => useEdgeReveal());

    // Default threshold is 6: y=7 must not arm the top edge.
    move(7);
    expect(result.current.topHot).toBe(false);
    move(6);
    expect(result.current.topHot).toBe(true);
  });
});
