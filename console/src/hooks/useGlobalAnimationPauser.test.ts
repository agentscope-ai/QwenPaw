import { renderHook } from "@testing-library/react";
import { describe, vi, beforeEach, afterEach, it, expect, Mock } from "vitest";
import { useGlobalAnimationPauser } from "./useGlobalAnimationPauser";

describe("useGlobalAnimationPauser", () => {
  let mockObserve: Mock;
  let mockUnobserve: Mock;
  let mockDisconnectIntersection: Mock;

  let mockMutationObserve: Mock;
  let mockMutationDisconnect: Mock;

  let intersectionCallback: (entries: any[]) => void;

  beforeEach(() => {
    mockObserve = vi.fn();
    mockUnobserve = vi.fn();
    mockDisconnectIntersection = vi.fn();
    mockMutationObserve = vi.fn();
    mockMutationDisconnect = vi.fn();

    // Mock IntersectionObserver
    class MockIntersectionObserver {
      constructor(callback: any) {
        intersectionCallback = callback;
      }
      observe = mockObserve;
      unobserve = mockUnobserve;
      disconnect = mockDisconnectIntersection;
    }
    vi.stubGlobal("IntersectionObserver", MockIntersectionObserver);

    // Mock MutationObserver
    class MockMutationObserver {
      constructor(_callback: any) {}
      observe = mockMutationObserve;
      disconnect = mockMutationDisconnect;
    }
    vi.stubGlobal("MutationObserver", MockMutationObserver);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("should initialize observers on mount and disconnect on unmount", () => {
    const { unmount } = renderHook(() => useGlobalAnimationPauser());

    expect(mockMutationObserve).toHaveBeenCalledWith(document.body, {
      childList: true,
      subtree: true,
    });

    unmount();

    expect(mockDisconnectIntersection).toHaveBeenCalled();
    expect(mockMutationDisconnect).toHaveBeenCalled();
  });

  it("should pause animation when offscreen and resume when onscreen", () => {
    renderHook(() => useGlobalAnimationPauser());

    // Create a mock element to represent the spinner
    const spinElement = document.createElement("div");
    spinElement.className = "ant-spin-dot-spin";

    // Simulate offscreen
    intersectionCallback([
      {
        target: spinElement,
        isIntersecting: false,
      },
    ]);

    expect(spinElement.style.animationPlayState).toBe("paused");

    // Simulate onscreen
    intersectionCallback([
      {
        target: spinElement,
        isIntersecting: true,
      },
    ]);

    expect(spinElement.style.animationPlayState).toBe("running");
  });

  it("should not crash if observers are unsupported", () => {
    vi.stubGlobal("IntersectionObserver", undefined);

    const { unmount } = renderHook(() => useGlobalAnimationPauser());

    expect(mockMutationObserve).not.toHaveBeenCalled();
    unmount();
    expect(mockDisconnectIntersection).not.toHaveBeenCalled();
  });
});
