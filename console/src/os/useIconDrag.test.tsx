import {
  describe,
  it,
  expect,
  beforeAll,
  beforeEach,
  afterEach,
  vi,
} from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { useIconDrag } from "./useIconDrag";

/** jsdom lacks the pointer-capture API used by the drag handlers. */
beforeAll(() => {
  Element.prototype.setPointerCapture = vi.fn();
  Element.prototype.releasePointerCapture = vi.fn();
});

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

function Harness({
  setPosition,
  onDragEnd,
}: {
  setPosition: (id: string, x: number, y: number) => void;
  onDragEnd?: (
    id: string,
    event: React.PointerEvent,
    moved: boolean,
  ) => boolean;
}) {
  const handlers = useIconDrag(setPosition, 28, onDragEnd);
  return (
    <div
      data-testid="icon"
      style={{ position: "absolute", left: 10, top: 40 }}
      {...handlers("core.chat", { x: 10, y: 40 })}
    />
  );
}

describe("useIconDrag", () => {
  it("moves via the DOM only and persists once on pointerup", () => {
    const setPosition = vi.fn();
    render(<Harness setPosition={setPosition} />);
    const icon = screen.getByTestId("icon");

    // Grab at (20,50): 10px inside the icon at (10,40).
    fireEvent.pointerDown(icon, { pointerId: 1, clientX: 20, clientY: 50 });
    fireEvent.pointerMove(icon, { pointerId: 1, clientX: 60, clientY: 90 });
    fireEvent.pointerMove(icon, { pointerId: 1, clientX: 120, clientY: 150 });

    // Mid-gesture: zero persisted writes.
    expect(setPosition).not.toHaveBeenCalled();
    // Visual position advances via rAF-coalesced DOM writes.
    vi.advanceTimersByTime(32);
    expect(icon.style.left).toBe("110px");
    expect(icon.style.top).toBe("140px");

    fireEvent.pointerUp(icon, { pointerId: 1, clientX: 120, clientY: 150 });
    expect(setPosition).toHaveBeenCalledTimes(1);
    expect(setPosition).toHaveBeenCalledWith("core.chat", 110, 140);
  });

  it("keeps clicks within the slop free of any write", () => {
    const setPosition = vi.fn();
    render(<Harness setPosition={setPosition} />);
    const icon = screen.getByTestId("icon");

    fireEvent.pointerDown(icon, { pointerId: 1, clientX: 20, clientY: 50 });
    fireEvent.pointerMove(icon, { pointerId: 1, clientX: 22, clientY: 51 });
    fireEvent.pointerUp(icon, { pointerId: 1, clientX: 22, clientY: 51 });

    expect(setPosition).not.toHaveBeenCalled();
  });

  it("pointercancel commits the last position exactly once", () => {
    const setPosition = vi.fn();
    render(<Harness setPosition={setPosition} />);
    const icon = screen.getByTestId("icon");

    fireEvent.pointerDown(icon, { pointerId: 1, clientX: 20, clientY: 50 });
    fireEvent.pointerMove(icon, { pointerId: 1, clientX: 80, clientY: 100 });
    fireEvent.pointerCancel(icon, { pointerId: 1 });
    // The capture-release cascade re-enters the finalizer.
    fireEvent.lostPointerCapture(icon, { pointerId: 1 });

    expect(setPosition).toHaveBeenCalledTimes(1);
    expect(setPosition).toHaveBeenCalledWith("core.chat", 70, 90);
  });

  it("restores the desktop position when a drop target handles the drag", () => {
    const setPosition = vi.fn();
    const onDragEnd = vi.fn(() => true);
    render(<Harness setPosition={setPosition} onDragEnd={onDragEnd} />);
    const icon = screen.getByTestId("icon");

    fireEvent.pointerDown(icon, { pointerId: 1, clientX: 20, clientY: 50 });
    fireEvent.pointerMove(icon, { pointerId: 1, clientX: 80, clientY: 100 });
    vi.advanceTimersByTime(32);
    fireEvent.pointerUp(icon, { pointerId: 1, clientX: 80, clientY: 100 });

    expect(onDragEnd).toHaveBeenCalledWith(
      "core.chat",
      expect.anything(),
      true,
    );
    expect(setPosition).not.toHaveBeenCalled();
    expect(icon.style.left).toBe("10px");
    expect(icon.style.top).toBe("40px");
  });
});
