import { act, render, screen } from "@testing-library/react";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { ViewportRenderBoundary } from "./ViewportRenderBoundary";

describe("ViewportRenderBoundary", () => {
  const observe = vi.fn();
  const unobserve = vi.fn();
  const disconnect = vi.fn();
  let intersectionCallback: IntersectionObserverCallback;
  let observerCount = 0;

  beforeAll(() => {
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
      bottom: 360,
      height: 360,
      left: 0,
      right: 800,
      top: 0,
      width: 800,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    });

    vi.stubGlobal(
      "IntersectionObserver",
      class MockIntersectionObserver {
        constructor(callback: IntersectionObserverCallback) {
          intersectionCallback = callback;
          observerCount += 1;
        }

        observe = observe;
        unobserve = unobserve;
        disconnect = disconnect;
      },
    );
    vi.stubGlobal(
      "ResizeObserver",
      class MockResizeObserver {
        observe = vi.fn();
        unobserve = vi.fn();
        disconnect = disconnect;
      },
    );
  });

  afterAll(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("shares one observer and preserves measured height offscreen", () => {
    const { container } = render(
      <>
        <ViewportRenderBoundary>
          <div>first expensive card</div>
        </ViewportRenderBoundary>
        <ViewportRenderBoundary>
          <div>second expensive card</div>
        </ViewportRenderBoundary>
      </>,
    );
    const boundaries = container.querySelectorAll(
      "[data-chat-viewport-content]",
    );

    expect(observerCount).toBe(1);
    expect(observe).toHaveBeenCalledTimes(2);

    act(() => {
      intersectionCallback(
        [
          {
            isIntersecting: false,
            target: boundaries[0],
          } as IntersectionObserverEntry,
        ],
        {} as IntersectionObserver,
      );
    });

    expect(screen.queryByText("first expensive card")).not.toBeInTheDocument();
    expect(screen.getByText("second expensive card")).toBeInTheDocument();
    expect(boundaries[0]).toHaveAttribute(
      "data-chat-viewport-content",
      "deferred",
    );
    expect(boundaries[0]).toHaveStyle({ height: "360px" });

    act(() => {
      intersectionCallback(
        [
          {
            isIntersecting: true,
            target: boundaries[0],
          } as IntersectionObserverEntry,
        ],
        {} as IntersectionObserver,
      );
    });

    expect(screen.getByText("first expensive card")).toBeInTheDocument();
  });
});
