import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PressFeedback } from "./PressFeedback";

vi.mock("motion", () => ({
  animate: vi.fn(
    (
      element: HTMLElement,
      values: { scale: number },
      options: { onComplete: () => void },
    ) => {
      element.style.scale = String(values.scale);
      queueMicrotask(options.onComplete);
      return { stop: vi.fn() };
    },
  ),
}));
afterEach(() => vi.restoreAllMocks());

describe("PressFeedback", () => {
  it("resets a held button when reduced motion becomes enabled after compression settles", async () => {
    const preference = new EventTarget();
    vi.spyOn(window, "matchMedia").mockReturnValue(
      Object.assign(preference, { matches: false }) as MediaQueryList,
    );
    render(
      <>
        <PressFeedback />
        <button data-press>Action</button>
      </>,
    );
    const button = screen.getByRole("button");
    fireEvent.keyDown(button, { key: " " });
    await act(async () => {});
    expect(button.style.scale).toBe("0.96");
    act(() => preference.dispatchEvent(new Event("change")));
    expect(button.style.scale).toBe("1");
  });
  it("releases keyboard compression when focus leaves the button", async () => {
    render(
      <>
        <PressFeedback />
        <button data-press>Action</button>
      </>,
    );
    const button = screen.getByRole("button");
    fireEvent.keyDown(button, { key: " " });
    await act(async () => {});
    fireEvent.focusOut(button);
    expect(button.style.scale).toBe("1");
  });
});
