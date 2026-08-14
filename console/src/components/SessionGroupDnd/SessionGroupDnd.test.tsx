import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SessionGroupDndProvider } from "./index";

vi.mock("@dnd-kit/core", () => ({
  DndContext: ({ children, onDragEnd, onDragOver }: any) => (
    <div>
      {children}
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
  it("expands the target group and moves only the dragged session", () => {
    const onMove = vi.fn();
    const onGroupHover = vi.fn();
    render(
      <SessionGroupDndProvider onMove={onMove} onGroupHover={onGroupHover}>
        <span>session list</span>
      </SessionGroupDndProvider>,
    );

    fireEvent.click(screen.getByText("hover target"));
    fireEvent.click(screen.getByText("drop target"));

    expect(onGroupHover).toHaveBeenCalledWith("research");
    expect(onMove).toHaveBeenCalledWith("session-1", "research");
  });
});
