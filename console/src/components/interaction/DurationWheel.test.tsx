// @vitest-environment jsdom
import { act, render, fireEvent } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DurationWheel } from "./DurationWheel";
const preferences = vi.hoisted(() => ({ reduced: false }));
vi.mock("motion/react", () => ({
  useReducedMotion: () => preferences.reduced,
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
afterEach(() => {
  vi.useRealTimers();
  preferences.reduced = false;
});

describe("DurationWheel external selections", () => {
  it("rolls through intermediate positions and can retarget before settling", () => {
    vi.useFakeTimers({
      toFake: ["requestAnimationFrame", "cancelAnimationFrame", "performance"],
    });
    const onChange = vi.fn();
    const view = render(<DurationWheel value={300} onChange={onChange} />);
    const position = () =>
      view.container.querySelector<HTMLElement>("[data-rwp-highlight-list]")!
        .style.transform;
    const initial = position();
    onChange.mockClear();
    view.rerender(<DurationWheel value={720} onChange={onChange} />);
    expect(position()).toBe(initial);
    act(() => vi.advanceTimersByTime(160));
    const intermediate = position();
    expect(intermediate).not.toBe(initial);
    view.rerender(<DurationWheel value={180} onChange={onChange} />);
    expect(position()).toBe(intermediate);
    act(() => vi.advanceTimersByTime(1000));
    const settled = position();
    expect(settled).not.toBe(intermediate);
    // Animating presentation must not emit intermediate configuration values.
    expect(onChange).not.toHaveBeenCalled();
    view.unmount();
    const reference = render(<DurationWheel value={180} />);
    expect(
      reference.container.querySelector<HTMLElement>(
        "[data-rwp-highlight-list]",
      )!.style.transform,
    ).toBe(settled);
  });

  it("updates directly when reduced motion is requested", () => {
    preferences.reduced = true;
    const view = render(<DurationWheel value={300} />);
    const initial = view.container.querySelector<HTMLElement>(
      "[data-rwp-highlight-list]",
    )!.style.transform;
    view.rerender(<DurationWheel value={720} />);
    expect(
      view.container.querySelector<HTMLElement>("[data-rwp-highlight-list]")!
        .style.transform,
    ).not.toBe(initial);
  });
});

describe("DurationWheel release momentum", () => {
  function setupGesture() {
    vi.useFakeTimers({
      toFake: [
        "requestAnimationFrame",
        "cancelAnimationFrame",
        "performance",
        "Date",
      ],
    });
    const onChange = vi.fn();
    const view = render(<DurationWheel value={300} onChange={onChange} />);
    const picker = view.container.querySelector<HTMLElement>("[data-rwp]")!;
    const position = () =>
      picker.querySelector<HTMLElement>("[data-rwp-highlight-list]")!.style
        .transform;
    onChange.mockClear();
    fireEvent.mouseDown(picker, { clientY: 150 });
    act(() => vi.advanceTimersByTime(20));
    fireEvent.mouseMove(document, { clientY: 78 });
    return { picker, position, onChange };
  }

  it("coasts after a quick flick, and pressing catches it immediately", () => {
    const { picker, position, onChange } = setupGesture();
    const held = position();
    act(() => vi.advanceTimersByTime(20));
    expect(position()).toBe(held);
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.mouseUp(document, { clientY: 78 });
    act(() => vi.advanceTimersByTime(100));
    expect(position()).not.toBe(held);
    fireEvent.mouseDown(picker, { clientY: 150 });
    const caught = position();
    act(() => vi.advanceTimersByTime(300));
    expect(position()).toBe(caught);
  });

  it("does not reuse stale velocity after dragging and holding still", () => {
    const { position, onChange } = setupGesture();
    const held = position();
    act(() => vi.advanceTimersByTime(200));
    fireEvent.mouseUp(document, { clientY: 78 });
    act(() => vi.advanceTimersByTime(800));
    expect(position()).toBe(held);
    expect(onChange).toHaveBeenCalledWith(360);
  });
});
