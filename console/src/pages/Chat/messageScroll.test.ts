import { afterEach, describe, expect, it, vi } from "vitest";
import {
  getNextReverseScrollTop,
  preserveReverseMessageViewport,
  scrollReverseMessageList,
} from "./messageScroll";

afterEach(() => {
  document.body.innerHTML = "";
});

describe("preserveReverseMessageViewport", () => {
  function fixture() {
    const { root, scroller, content } = createReverseScroller();
    content.remove();
    let height = 1300;
    const rect = (top: number, size: number) => new DOMRect(0, top, 600, size);
    const addBubble = (id: string, fromBottom: number, size: number) => {
      const bubble = document.createElement("div");
      bubble.id = id;
      bubble.dataset.role = "assistant";
      bubble.getBoundingClientRect = () =>
        rect(500 - fromBottom - scroller.scrollTop, size);
      scroller.append(bubble);
      return bubble;
    };
    Object.defineProperty(scroller, "scrollHeight", { get: () => height });
    scroller.getBoundingClientRect = () => rect(0, 500);
    addBubble("newest", 500, 500);
    const anchor = addBubble("reading", 1000, 500);
    addBubble("oldest", 1300, 300);
    scroller.scrollTop = -450;

    let resize!: () => void;
    const observer = vi.mocked(ResizeObserver);
    observer.mockImplementationOnce(function (
      callback: ResizeObserverCallback,
    ) {
      resize = () => callback([], this);
      return { observe: vi.fn(), disconnect: vi.fn(), unobserve: vi.fn() };
    });
    const disconnect = preserveReverseMessageViewport(root);
    return {
      scroller,
      anchor,
      addBubble,
      disconnect,
      resize,
      setHeight: (next: number) => (height = next),
    };
  }

  it("preserves the same bubble and offset after height changes and clamping", () => {
    const { scroller, anchor, resize, disconnect, setHeight } = fixture();
    try {
      expect(anchor.getBoundingClientRect().top).toBe(-50);
      setHeight(800);
      anchor.getBoundingClientRect = () =>
        new DOMRect(0, -scroller.scrollTop - 250, 600, 300);
      scroller.scrollTop = -300;
      scroller.dispatchEvent(new Event("scroll"));
      resize();
      expect(scroller.scrollTop).toBe(-200);
      expect(anchor.getBoundingClientRect().top).toBe(-50);
    } finally {
      disconnect();
    }
  });

  it("preserves a replaced bubble by ID but falls back when it disappears", async () => {
    const { scroller, anchor, addBubble, disconnect } = fixture();
    try {
      anchor.replaceWith(addBubble("reading", 950, 450));
      await Promise.resolve();
      expect(scroller.scrollTop).toBe(-400);
      scroller.children.namedItem("reading")?.remove();
      await Promise.resolve();
      expect(scroller.scrollTop).toBe(0);
    } finally {
      disconnect();
    }
  });

  it("honors return to latest before restored history changes the layout", async () => {
    const { scroller, addBubble, disconnect } = fixture();
    try {
      addBubble("newest-reply", 250, 250);
      scroller.scrollTop = 0;
      scroller.dispatchEvent(new Event("qwenpaw:chat-scroll-to-latest"));
      await Promise.resolve();
      expect(scroller.scrollTop).toBe(0);
    } finally {
      disconnect();
    }
  });

  it("keeps following the newest message after an explicit scroll to bottom", () => {
    const { scroller, resize, disconnect } = fixture();
    try {
      scroller.scrollTop = 0;
      scroller.dispatchEvent(new Event("scroll"));
      resize();
      expect(scroller.scrollTop).toBe(0);
    } finally {
      disconnect();
    }
  });
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
  it("does not resolve styles for non-scrollable message ancestors", () => {
    const { content, root, scroller } = createReverseScroller();
    const getComputedStyleSpy = vi.spyOn(window, "getComputedStyle");
    scroller.scrollTop = -420;

    expect(scrollReverseMessageList(root, content, 100, 0)).toBe(true);
    expect(getComputedStyleSpy).not.toHaveBeenCalled();

    getComputedStyleSpy.mockRestore();
  });

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
