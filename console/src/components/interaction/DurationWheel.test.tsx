import { act, fireEvent, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DurationWheel } from "./DurationWheel";

const preferences = vi.hoisted(() => ({ reduced: false }));
vi.mock("motion/react", () => ({
  useReducedMotion: () => preferences.reduced,
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

beforeEach(() => {
  vi.spyOn(HTMLElement.prototype, "scrollTo");
});
afterEach(() => {
  vi.restoreAllMocks();
  preferences.reduced = false;
});

function settle(element: HTMLElement, row: number) {
  fireEvent.wheel(element, { deltaY: 72 });
  element.scrollTop = row * 72;
  fireEvent.scroll(element);
  act(() => element.dispatchEvent(new Event("scrollend")));
}

describe("DurationWheel", () => {
  it("initializes without saving and animates external selections without emitting edits", () => {
    const onChange = vi.fn();
    const view = render(<DurationWheel value={300} onChange={onChange} />);
    const hour = view.getAllByRole("spinbutton")[0];
    expect(hour.scrollTop).toBe(29 * 72);
    view.rerender(<DurationWheel value={720} onChange={onChange} />);
    expect(hour.scrollTo).toHaveBeenCalledWith({
      top: 36 * 72,
      behavior: "smooth",
    });
    act(() => hour.dispatchEvent(new Event("scrollend")));
    expect(onChange).not.toHaveBeenCalled();
    view.rerender(<DurationWheel value={180} onChange={onChange} />);
    expect(hour).toHaveAttribute("aria-valuenow", "3");
  });

  it("commits only the settled selection and wraps minutes without changing hours", () => {
    const onChange = vi.fn();
    const view = render(<DurationWheel value={359} onChange={onChange} />);
    const minute = view.getAllByRole("spinbutton")[1];
    fireEvent.wheel(minute, { deltaY: 72 });
    minute.scrollTop = 120 * 72;
    fireEvent.scroll(minute);
    expect(onChange).not.toHaveBeenCalled();
    act(() => minute.dispatchEvent(new Event("scrollend")));
    expect(onChange).toHaveBeenCalledExactlyOnceWith(300);
    expect(minute.scrollTop).toBe(60 * 72);
    act(() => minute.dispatchEvent(new Event("scrollend")));
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("allows user scrolling to interrupt an external selection", () => {
    const onChange = vi.fn();
    const view = render(<DurationWheel value={300} onChange={onChange} />);
    view.rerender(<DurationWheel value={720} onChange={onChange} />);
    settle(view.getAllByRole("spinbutton")[0], 31);
    expect(onChange).toHaveBeenCalledExactlyOnceWith(420);
  });

  it("supports keyboard wrap, long intervals, and disabled values", () => {
    const onChange = vi.fn();
    const view = render(<DurationWheel value={0} onChange={onChange} />);
    fireEvent.keyDown(view.getAllByRole("spinbutton")[0], { key: "ArrowUp" });
    expect(onChange).toHaveBeenLastCalledWith(1380);
    view.rerender(
      <DurationWheel value={2880} maxHours={48} onChange={onChange} />,
    );
    const hour = view.getAllByRole("spinbutton")[0];
    expect(hour).toHaveAttribute("aria-valuenow", "48");
    fireEvent.keyDown(hour, { key: "ArrowDown" });
    expect(onChange).toHaveBeenLastCalledWith(0);
    view.rerender(<DurationWheel value={2880} maxHours={48} disabled />);
    expect(view.queryAllByRole("spinbutton")).toHaveLength(0);
    expect(view.getByText("48")).toBeVisible();
  });

  it("uses instant external scrolling with reduced motion", () => {
    preferences.reduced = true;
    const view = render(<DurationWheel value={300} />);
    view.rerender(<DurationWheel value={720} />);
    expect(
      view.getAllByRole("spinbutton")[0].scrollTo,
    ).toHaveBeenLastCalledWith({ top: 36 * 72, behavior: "instant" });
  });
});
