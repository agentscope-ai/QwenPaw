import { afterEach, describe, expect, it, vi } from "vitest";
import { followInitialHistoryBottom } from "./initialHistoryBottom";

describe("initial history bottom", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    document.body.replaceChildren();
  });

  function setup() {
    let resize = () => {};
    const disconnect = vi.fn();
    vi.stubGlobal(
      "ResizeObserver",
      class {
        constructor(callback: () => void) {
          resize = callback;
        }
        observe() {}
        disconnect = disconnect;
      },
    );
    const surface = document.createElement("div");
    surface.className = "qwenpaw-chat-anywhere-layout-right";
    const scroll = document.createElement("div");
    scroll.append(document.createElement("div"));
    surface.append(scroll);
    document.body.append(surface);
    let height = 0;
    let content = 1000;
    Object.defineProperties(scroll, {
      clientHeight: { get: () => height },
      scrollHeight: { get: () => content },
    });
    return {
      scroll,
      surface,
      resize: (viewport: number, total: number) => {
        height = viewport;
        content = total;
        resize();
      },
    };
  }

  it("waits for a visible viewport and follows later message measurements", () => {
    const { scroll, resize } = setup();
    const stop = followInitialHistoryBottom(scroll);
    expect(scroll.scrollTop).toBe(0);
    resize(800, 2000);
    expect(scroll.scrollTop).toBe(2000);
    resize(800, 3200);
    expect(scroll.scrollTop).toBe(3200);
    stop();
  });

  it.each(["wheel", "pointerdown", "touchstart", "keydown"])(
    "never reclaims the anchor after %s, including navigation controls",
    (type) => {
      const { scroll, surface, resize } = setup();
      const stop = followInitialHistoryBottom(scroll);
      resize(800, 2000);
      surface.dispatchEvent(new Event(type, { bubbles: true }));
      scroll.scrollTop = 100;
      resize(800, 3200);
      scroll.dispatchEvent(new Event("chat-message-window-rendered"));
      expect(scroll.scrollTop).toBe(100);
      stop();
    },
  );

  it("cleans up on conversation switch", () => {
    const { scroll, resize } = setup();
    const stop = followInitialHistoryBottom(scroll);
    stop();
    resize(800, 2000);
    expect(scroll.scrollTop).toBe(0);
  });
});
