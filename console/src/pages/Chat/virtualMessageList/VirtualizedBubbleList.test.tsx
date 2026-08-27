import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import VirtualizedBubbleList from "./VirtualizedBubbleList";

function row(item: { id: string }) {
  return <div>{item.id}</div>;
}

function makeItems(from: number, to: number) {
  const items: { id: string }[] = [];
  for (let index = to; index >= from; index -= 1) {
    items.push({ id: `msg-${index}` });
  }
  return items;
}

function setScrollerMetrics(
  scroller: HTMLElement,
  scrollHeight: number,
  clientHeight: number,
) {
  Object.defineProperties(scroller, {
    scrollHeight: { configurable: true, value: scrollHeight },
    clientHeight: { configurable: true, value: clientHeight },
  });
}

describe("VirtualizedBubbleList", () => {
  it("only mounts viewport plus overscan rows", () => {
    render(
      <VirtualizedBubbleList
        items={makeItems(0, 49)}
        estimatedRowHeight={100}
        gap={0}
        overscanPx={250}
        renderItem={row}
      />,
    );

    const mounted = screen.getAllByTestId("virtual-message-row");
    expect(mounted.length).toBeGreaterThan(0);
    expect(mounted.length).toBeLessThan(50);
    expect(document.querySelector('[data-message-id="msg-49"]')).toBeTruthy();
    expect(document.querySelector('[data-message-id="msg-0"]')).toBeNull();
  });

  it("keeps reverse-list scrollTop when older messages are prepended", () => {
    function Harness() {
      const [items, setItems] = useState(makeItems(20, 39));
      return (
        <div>
          <button type="button" onClick={() => setItems(makeItems(0, 39))}>
            prepend
          </button>
          <VirtualizedBubbleList
            items={items}
            estimatedRowHeight={100}
            gap={0}
            overscanPx={200}
            renderItem={row}
          />
        </div>
      );
    }

    render(<Harness />);
    const scroller = screen.getByTestId("virtual-message-list");
    scroller.scrollTop = -240;
    fireEvent.scroll(scroller);
    fireEvent.click(screen.getByText("prepend"));
    expect(scroller.scrollTop).toBe(-240);
  });

  it("requests earlier history when the user scrolls to the oldest edge", () => {
    const onStartReached = vi.fn();
    render(
      <VirtualizedBubbleList
        items={makeItems(0, 19)}
        estimatedRowHeight={100}
        gap={0}
        overscanPx={100}
        onStartReached={onStartReached}
        renderItem={row}
      />,
    );
    const scroller = screen.getByTestId("virtual-message-list");
    setScrollerMetrics(scroller, 2000, 400);
    scroller.scrollTop = -1580;
    fireEvent.scroll(scroller);
    expect(onStartReached).toHaveBeenCalledTimes(1);

    scroller.scrollTop = -10;
    fireEvent.scroll(scroller);
    expect(onStartReached).toHaveBeenCalledTimes(1);

    scroller.scrollTop = -1580;
    fireEvent.scroll(scroller);
    expect(onStartReached).toHaveBeenCalledTimes(2);
  });

  it("keeps scrollTop at the newest edge when a new message arrives", () => {
    function Harness() {
      const [items, setItems] = useState(makeItems(0, 9));
      return (
        <div>
          <button
            type="button"
            onClick={() =>
              setItems((current) => [{ id: "msg-live" }, ...current])
            }
          >
            append-newest
          </button>
          <VirtualizedBubbleList
            items={items}
            estimatedRowHeight={100}
            gap={0}
            overscanPx={200}
            renderItem={row}
          />
        </div>
      );
    }

    render(<Harness />);
    const scroller = screen.getByTestId("virtual-message-list");
    expect(scroller.scrollTop).toBe(0);
    fireEvent.click(screen.getByText("append-newest"));
    expect(scroller.scrollTop).toBe(0);
    expect(document.querySelector('[data-message-id="msg-live"]')).toBeTruthy();
  });

  it("does not jump to newest when the user has scrolled into older history", () => {
    function Harness() {
      const [items, setItems] = useState(makeItems(0, 19));
      return (
        <div>
          <button
            type="button"
            onClick={() =>
              setItems((current) => [{ id: "msg-live" }, ...current])
            }
          >
            append-newest
          </button>
          <VirtualizedBubbleList
            items={items}
            estimatedRowHeight={100}
            gap={0}
            overscanPx={100}
            renderItem={row}
          />
        </div>
      );
    }

    render(<Harness />);
    const scroller = screen.getByTestId("virtual-message-list");
    setScrollerMetrics(scroller, 2000, 400);
    scroller.scrollTop = -320;
    fireEvent.scroll(scroller);
    fireEvent.click(screen.getByText("append-newest"));
    // New row at the newest edge is 100px; keep the same older row in view.
    expect(scroller.scrollTop).toBe(-420);
  });

  it("marks the newest desc row as isLast", () => {
    const renderItem = vi.fn((item: { id: string }) => <div>{item.id}</div>);
    render(
      <VirtualizedBubbleList
        items={makeItems(0, 4)}
        estimatedRowHeight={100}
        gap={0}
        overscanPx={400}
        renderItem={renderItem}
      />,
    );
    const lastCalls = renderItem.mock.calls.filter((call) => call[2] === true);
    expect(lastCalls).toHaveLength(1);
    expect(lastCalls[0][0]).toEqual({ id: "msg-4" });
    expect(lastCalls[0][1]).toBe(0);
  });

  it("disconnects observers when remounted for a new session", () => {
    const disconnect = vi.fn();
    const Original = globalThis.ResizeObserver;
    class MockResizeObserver {
      observe = vi.fn();
      unobserve = vi.fn();
      disconnect = disconnect;
    }
    globalThis.ResizeObserver =
      MockResizeObserver as unknown as typeof ResizeObserver;

    try {
      const { rerender } = render(
        <VirtualizedBubbleList
          key="session-a"
          items={makeItems(0, 8)}
          estimatedRowHeight={100}
          gap={0}
          overscanPx={200}
          renderItem={row}
        />,
      );
      const afterFirst = disconnect.mock.calls.length;
      rerender(
        <VirtualizedBubbleList
          key="session-b"
          items={makeItems(0, 8)}
          estimatedRowHeight={100}
          gap={0}
          overscanPx={200}
          renderItem={row}
        />,
      );
      expect(disconnect.mock.calls.length).toBeGreaterThan(afterFirst);
    } finally {
      globalThis.ResizeObserver = Original;
    }
  });

  it("uses the reverse-list class names the wheel handler looks up", () => {
    render(
      <VirtualizedBubbleList
        items={makeItems(0, 4)}
        classNames={{
          list: "qwenpaw-chat-anywhere-message-list-bubble-scroll",
        }}
        estimatedRowHeight={100}
        gap={0}
        overscanPx={400}
        renderItem={row}
      />,
    );
    const scroller = screen.getByTestId("virtual-message-list");
    expect(
      scroller.matches(
        '[class*="chat-anywhere-message-list-bubble-scroll"]' +
          '[class*="bubble-list-order-desc"]',
      ),
    ).toBe(true);
  });

  it("disconnects ResizeObservers on unmount", () => {
    const disconnect = vi.fn();
    const Original = globalThis.ResizeObserver;
    class MockResizeObserver {
      observe = vi.fn();
      unobserve = vi.fn();
      disconnect = disconnect;
    }
    globalThis.ResizeObserver =
      MockResizeObserver as unknown as typeof ResizeObserver;

    try {
      const { unmount } = render(
        <VirtualizedBubbleList
          items={makeItems(0, 8)}
          estimatedRowHeight={100}
          gap={0}
          overscanPx={200}
          renderItem={row}
        />,
      );
      expect(disconnect).not.toHaveBeenCalled();
      unmount();
      expect(disconnect).toHaveBeenCalled();
    } finally {
      globalThis.ResizeObserver = Original;
    }
  });

  it("does not call onStartReached after unmount", () => {
    const onStartReached = vi.fn();
    const { unmount } = render(
      <VirtualizedBubbleList
        items={makeItems(0, 19)}
        estimatedRowHeight={100}
        gap={0}
        overscanPx={100}
        onStartReached={onStartReached}
        renderItem={row}
      />,
    );
    const scroller = screen.getByTestId("virtual-message-list");
    setScrollerMetrics(scroller, 2000, 400);
    unmount();
    scroller.scrollTop = -1580;
    fireEvent.scroll(scroller);
    expect(onStartReached).not.toHaveBeenCalled();
  });
});
