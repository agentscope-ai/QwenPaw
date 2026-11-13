import { afterEach, describe, expect, it, vi } from "vitest";
import { attachBottomFollow, distanceFromBottom } from "./bottomFollow";

describe("Chat bottom following", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    document.body.replaceChildren();
  });
  function setup(reverse = false) {
    const frames = new Map<number, FrameRequestCallback>();
    let id = 0;
    let changed = () => {};
    let now = 1000;
    vi.spyOn(performance, "now").mockImplementation(() => now);
    vi.stubGlobal("requestAnimationFrame", (fn: FrameRequestCallback) => {
      frames.set(++id, fn);
      return id;
    });
    vi.stubGlobal("cancelAnimationFrame", (key: number) => frames.delete(key));
    vi.stubGlobal(
      "ResizeObserver",
      class {
        constructor(fn: () => void) {
          changed = fn;
        }
        observe() {}
        disconnect() {}
      },
    );
    const scroll = document.createElement("div");
    if (reverse) scroll.className = "bubble-list-order-desc";
    document.body.append(scroll);
    let height = 1000;
    Object.defineProperties(scroll, {
      clientHeight: { value: 400 },
      scrollHeight: { get: () => height },
    });
    const report = vi.fn();
    const control = attachBottomFollow(scroll, report);
    const flush = () => {
      const pending = [...frames.values()];
      frames.clear();
      pending.forEach((fn) => fn(now));
    };
    return {
      scroll,
      report,
      control,
      flush,
      grow: () => {
        height += 300;
        changed();
      },
      tick: () => {
        now += 300;
      },
      manual: (top: number) => {
        scroll.dispatchEvent(new WheelEvent("wheel", { deltaY: -100 }));
        scroll.scrollTop = top;
        scroll.dispatchEvent(new Event("scroll"));
        flush();
      },
    };
  }
  it.each([false, true])(
    "starts pinned and hides the button, reverse=%s",
    (reverse) => {
      const s = setup(reverse);
      s.flush();
      expect(distanceFromBottom(s.scroll)).toBe(0);
      expect(s.report).toHaveBeenLastCalledWith(false);
      s.grow();
      s.flush();
      expect(distanceFromBottom(s.scroll)).toBe(0);
      s.control.dispose();
    },
  );
  it("follows within 24px but detaches beyond it", () => {
    const s = setup();
    s.flush();
    s.manual(580);
    s.grow();
    s.flush();
    expect(s.scroll.scrollTop).toBe(900);
    s.manual(850);
    s.tick();
    s.grow();
    s.flush();
    expect(s.scroll.scrollTop).toBe(850);
    expect(s.report).toHaveBeenLastCalledWith(true);
    s.control.resume();
    s.grow();
    s.flush();
    expect(distanceFromBottom(s.scroll)).toBe(0);
    s.control.dispose();
  });
  it("rejects SDK insertion scroll while detached, including after completion", () => {
    const s = setup(true);
    s.flush();
    s.manual(-100);
    s.tick();
    s.scroll.scrollTop = 0;
    s.scroll.dispatchEvent(new Event("scroll"));
    expect(s.scroll.scrollTop).toBe(-100);
    s.grow();
    s.flush();
    expect(s.scroll.scrollTop).toBe(-100);
    s.manual(0);
    s.grow();
    s.flush();
    expect(s.scroll.scrollTop).toBe(0);
    s.control.dispose();
  });
  it("keeps a directory target and cleans up pending frames", () => {
    const s = setup();
    s.flush();
    s.scroll.scrollTop = 100;
    s.scroll.dispatchEvent(new Event("chat-history-navigated"));
    s.grow();
    s.flush();
    expect(s.scroll.scrollTop).toBe(100);
    s.control.dispose();
    s.grow();
    s.flush();
    expect(s.scroll.scrollTop).toBe(100);
  });
});
