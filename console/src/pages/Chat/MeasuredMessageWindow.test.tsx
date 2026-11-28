import { act, fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  MeasuredMessageWindow,
  MESSAGE_WINDOW_LIMIT,
  RESPONSE_WINDOW_LIMIT,
} from "./MeasuredMessageWindow";

describe("measured message window", () => {
  afterEach(() => vi.restoreAllMocks());

  it("keeps the position restored by the history window after measuring rows", () => {
    const scroller = document.createElement("div");
    scroller.dataset.historyMessageWindow = "true";
    document.body.append(scroller);
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(
      function (this: HTMLElement) {
        const top = this.hasAttribute("data-window-row")
          ? -scroller.scrollTop
          : 0;
        return new DOMRect(0, top, 600, 300);
      },
    );
    scroller.addEventListener("chat-message-window-rendered", () => {
      scroller.scrollTop = 80;
    });
    render(
      <MeasuredMessageWindow ids={["reading"]}>
        {() => <article>Reading</article>}
      </MeasuredMessageWindow>,
      { container: scroller },
    );
    expect(scroller.scrollTop).toBe(80);
  });

  it("fills a tall viewport with short steps after measurement without another scroll", () => {
    vi.useFakeTimers();
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(
      1500,
    );
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(
      function (this: HTMLElement) {
        const index = Number(this.dataset.windowRow?.slice(2) ?? 0);
        return {
          top: index * 24,
          bottom: index * 24 + 24,
          height: this.hasAttribute("data-window-row") ? 24 : 1500,
        } as DOMRect;
      },
    );
    const view = render(
      <div data-history-message-window="true">
        <MeasuredMessageWindow
          ids={Array.from({ length: 1000 }, (_, i) => `m-${i}`)}
          estimate={120}
          maxItems={RESPONSE_WINDOW_LIMIT}
        >
          {(index) => <article>{index}</article>}
        </MeasuredMessageWindow>
      </div>,
    );
    for (let frame = 0; frame < 20; frame += 1) {
      act(() => vi.advanceTimersByTime(17));
    }
    const rows = view.container.querySelectorAll("[data-window-row]");
    expect(rows.length).toBeGreaterThan(MESSAGE_WINDOW_LIMIT);
    expect(rows.length).toBeLessThanOrEqual(RESPONSE_WINDOW_LIMIT);
    expect(
      rows[rows.length - 1].getBoundingClientRect().bottom,
    ).toBeGreaterThanOrEqual(1500);
    vi.useRealTimers();
  });

  it("bounds mounted bodies while moving in both directions", () => {
    vi.useFakeTimers();
    let top = 0;
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(
      function (this: HTMLElement) {
        return {
          top: this.dataset.measuredMessageWindow ? -top : 0,
          bottom: 0,
          height: 0,
        } as DOMRect;
      },
    );
    const view = render(
      <div data-history-message-window="true">
        <MeasuredMessageWindow
          ids={Array.from({ length: 1000 }, (_, i) => `m-${i}`)}
        >
          {(index) => <article>{index}</article>}
        </MeasuredMessageWindow>
      </div>,
    );
    const scroll = view.container.firstElementChild!;
    top = 240 * 500;
    act(() => {
      fireEvent.scroll(scroll);
      vi.runAllTimers();
    });
    expect(view.getByText("500")).toBeTruthy();
    expect(view.queryByText("0")).toBeNull();
    expect(view.container.querySelectorAll("article")).toHaveLength(
      MESSAGE_WINDOW_LIMIT,
    );
    top = 0;
    act(() => {
      fireEvent.scroll(scroll);
      vi.runAllTimers();
    });
    expect(view.getByText("0")).toBeTruthy();
    expect(view.queryByText("500")).toBeNull();
    expect(view.container.querySelectorAll("article")).toHaveLength(
      MESSAGE_WINDOW_LIMIT,
    );
    vi.useRealTimers();
  });
});
