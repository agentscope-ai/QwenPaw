import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SessionGroupDndProvider } from "./index";

vi.mock("@dnd-kit/core", () => ({
  DndContext: ({
    children,
    onDragStart,
    onDragEnd,
    onDragOver,
    onDragCancel,
  }: any) => (
    <div>
      {children}
      <button
        onClick={() =>
          onDragStart({
            active: {
              data: {
                current: {
                  sessionId: "session-1",
                  groupId: "work",
                  label: "Conversation",
                },
              },
            },
          })
        }
      >
        start dragging
      </button>
      <button
        onClick={() =>
          onDragOver({ over: { data: { current: { groupId: "research" } } } })
        }
      >
        hover target
      </button>
      <button
        onClick={() =>
          onDragEnd({
            active: {
              data: {
                current: {
                  sessionId: "session-1",
                  groupId: "work",
                  label: "Conversation",
                },
              },
            },
            over: { data: { current: { groupId: "research" } } },
          })
        }
      >
        drop target
      </button>
      <button onClick={onDragCancel}>cancel dragging</button>
    </div>
  ),
  DragOverlay: ({ children }: any) => children,
  MouseSensor: class {},
  TouchSensor: class {},
  useSensor: vi.fn(),
  useSensors: vi.fn(() => []),
  useDraggable: vi.fn(),
  useDroppable: vi.fn(),
}));

describe("SessionGroupDndProvider", () => {
  it("reports drag state and moves only the dragged session", () => {
    const onMove = vi.fn();
    const onDragStateChange = vi.fn();
    render(
      <SessionGroupDndProvider
        onMove={onMove}
        onDragStateChange={onDragStateChange}
      >
        <span>session list</span>
      </SessionGroupDndProvider>,
    );

    fireEvent.click(screen.getByText("start dragging"));
    fireEvent.click(screen.getByText("hover target"));
    fireEvent.click(screen.getByText("drop target"));

    expect(onDragStateChange).toHaveBeenNthCalledWith(1, true);
    expect(onDragStateChange).toHaveBeenNthCalledWith(2, false);
    expect(onMove).toHaveBeenCalledWith("session-1", "research");
  });

  it("restores the list when dragging is cancelled", () => {
    const onDragStateChange = vi.fn();
    render(
      <SessionGroupDndProvider
        onMove={vi.fn()}
        onDragStateChange={onDragStateChange}
      >
        <span>session list</span>
      </SessionGroupDndProvider>,
    );

    fireEvent.click(screen.getByText("start dragging"));
    fireEvent.click(screen.getByText("cancel dragging"));

    expect(onDragStateChange).toHaveBeenNthCalledWith(1, true);
    expect(onDragStateChange).toHaveBeenNthCalledWith(2, false);
  });
});
