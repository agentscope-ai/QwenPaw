import { afterEach, describe, expect, it } from "vitest";
import {
  getNextReverseScrollTop,
  scrollReverseMessageList,
} from "./messageScroll";

afterEach(() => {
  document.body.innerHTML = "";
});

describe("getNextReverseScrollTop", () => {
  it("moves a reverse list toward the newest message", () => {
    expect(getNextReverseScrollTop(-420, 1200, 500, 120, 0)).toBe(-300);
  });

  it("clamps downward scrolling to the newest message", () => {
    expect(getNextReverseScrollTop(-40, 1200, 500, 120, 0)).toBe(0);
  });

  it("clamps upward scrolling to the oldest message", () => {
    expect(getNextReverseScrollTop(-650, 1200, 500, -120, 0)).toBe(-700);
  });

  it("normalizes line and page wheel deltas", () => {
    expect(getNextReverseScrollTop(-400, 1200, 500, 2, 1)).toBe(-368);
    expect(getNextReverseScrollTop(-600, 1200, 500, 1, 2)).toBe(-100);
  });
});

function setElementMetrics(
  element: HTMLElement,
  scrollHeight: number,
  clientHeight: number,
): void {
  Object.defineProperties(element, {
    scrollHeight: { configurable: true, value: scrollHeight },
    clientHeight: { configurable: true, value: clientHeight },
  });
}

function createReverseScroller(): {
  content: HTMLElement;
  root: HTMLElement;
  scroller: HTMLElement;
} {
  const root = document.createElement("div");
  const scroller = document.createElement("div");
  const content = document.createElement("div");

  scroller.className =
    "qwenpaw-bubble-list-order-desc " +
    "qwenpaw-chat-anywhere-message-list-bubble-scroll";
  scroller.append(content);
  root.append(scroller);
  document.body.append(root);
  setElementMetrics(scroller, 1200, 500);

  return { content, root, scroller };
}

describe("scrollReverseMessageList", () => {
  it("applies wheel movement to the SDK reverse scroller", () => {
    const { content, root, scroller } = createReverseScroller();
    scroller.scrollTop = -420;

    expect(scrollReverseMessageList(root, content, 120, 0)).toBe(true);
    expect(scroller.scrollTop).toBe(-300);
  });

  it("handles subpixel trackpad movement over SVG message content", () => {
    const { content, root, scroller } = createReverseScroller();
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    content.append(svg);
    scroller.scrollTop = -10;

    expect(scrollReverseMessageList(root, svg, 0.5, 0)).toBe(true);
    expect(scroller.scrollTop).toBe(-9.5);
  });

  it("does not capture wheel input already handled by a nested scroller", () => {
    const { content, root, scroller } = createReverseScroller();
    const nestedScroller = document.createElement("div");
    nestedScroller.style.overflowY = "auto";
    nestedScroller.append(content);
    scroller.append(nestedScroller);
    setElementMetrics(nestedScroller, 400, 200);
    nestedScroller.scrollTop = 50;
    scroller.scrollTop = -420;

    expect(scrollReverseMessageList(root, content, 100, 0)).toBe(false);
    expect(scroller.scrollTop).toBe(-420);
  });

  it("ignores wheel input outside the message scroller", () => {
    const { root, scroller } = createReverseScroller();
    const outside = document.createElement("div");
    root.append(outside);
    scroller.scrollTop = -420;

    expect(scrollReverseMessageList(root, outside, 100, 0)).toBe(false);
    expect(scroller.scrollTop).toBe(-420);
  });
});
