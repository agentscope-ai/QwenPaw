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
  });
});
