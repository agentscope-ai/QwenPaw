import { act, fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  MeasuredMessageWindow,
  MESSAGE_WINDOW_LIMIT,
  RESPONSE_WINDOW_LIMIT,
  revealCachedMessage,
} from "./MeasuredMessageWindow";

describe("measured message window", () => {
  afterEach(() => vi.restoreAllMocks());

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

  it("reveals a cached navigation target without fetching another page", () => {
    const ready = vi.fn();
    const view = render(
      <div data-history-message-window="true">
        <MeasuredMessageWindow
          ids={Array.from({ length: 1000 }, (_, i) => `m-${i}`)}
        >
          {(index) => <article>{index}</article>}
        </MeasuredMessageWindow>
      </div>,
    );
    expect(view.queryByText("500")).toBeNull();
    act(() => {
      expect(
        revealCachedMessage(
          view.container.firstElementChild as HTMLElement,
          "m-500",
          ready,
        ),
      ).toBe(true);
    });
    expect(view.getByText("500")).toBeTruthy();
    expect(ready).toHaveBeenCalledOnce();
    expect(view.container.querySelectorAll("article")).toHaveLength(
      MESSAGE_WINDOW_LIMIT,
    );
  });

  it("bounds mounted bodies after repeated prepend and append", () => {
    const list = (count: number) => (
      <div data-history-message-window="true">
        <MeasuredMessageWindow
          ids={Array.from({ length: count }, (_, i) => `m-${i}`)}
          initialEnd
        >
          {(index) => <article>{index}</article>}
        </MeasuredMessageWindow>
      </div>
    );
    const view = render(list(100));
    for (const count of [500, 1000, 2000]) {
      view.rerender(list(count));
      expect(view.container.querySelectorAll("article")).toHaveLength(
        MESSAGE_WINDOW_LIMIT,
      );
      expect(
        view.container.querySelectorAll('[aria-hidden="true"]'),
      ).toHaveLength(2);
    }
  });

  it("moves the mounted slice in both directions without retaining old bodies", () => {
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
    top = 0;
    act(() => {
      fireEvent.scroll(scroll);
      vi.runAllTimers();
    });
    expect(view.getByText("0")).toBeTruthy();
    expect(view.queryByText("500")).toBeNull();
    vi.useRealTimers();
  });
});
