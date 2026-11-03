import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { DraggableSession, SessionGroupDndProvider } from "./index";

const { mockMeasureDroppableContainers, mockPointerDown } = vi.hoisted(() => ({
  mockMeasureDroppableContainers: vi.fn(),
  mockPointerDown: vi.fn(),
}));

vi.mock("@dnd-kit/core", () => ({
  DndContext: ({
    children,
    onDragStart,
    onDragEnd,
    onDragOver,
    onDragCancel,
    measuring,
  }: {
    children: ReactNode;
    onDragStart: (event: unknown) => void;
    onDragEnd: (event: unknown) => void;
    onDragOver: (event: unknown) => void;
    onDragCancel: () => void;
    measuring?: { droppable?: { strategy?: string } };
  }) => (
    <div
      data-testid="dnd-context"
      data-measuring-strategy={measuring?.droppable?.strategy}
    >
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
          onDragOver({ over: { data: { current: { groupId: "new-group" } } } })
        }
      >
        hover target
      </button>
      <button
        onClick={() =>
          onDragEnd({
            active: {
              data: { current: {} },
            },
            over: { data: { current: { groupId: "new-group" } } },
          })
        }
      >
        drop target
      </button>
      <button onClick={onDragCancel}>cancel dragging</button>
    </div>
  ),
  DragOverlay: ({ children }: { children: ReactNode }) => children,
  MeasuringStrategy: { Always: "always" },
  MouseSensor: class {},
  TouchSensor: class {},
  useSensor: vi.fn(),
  useSensors: vi.fn(() => []),
  useDndContext: vi.fn(() => ({
    measureDroppableContainers: mockMeasureDroppableContainers,
  })),
  useDraggable: vi.fn(() => ({
    attributes: {
      "aria-describedby": "DndDescribedBy-0",
      role: "button",
      tabIndex: 0,
    },
    isDragging: false,
    listeners: { onPointerDown: mockPointerDown },
    setNodeRef: vi.fn(),
    transform: null,
  })),
  useDroppable: vi.fn(),
}));

describe("SessionGroupDndProvider", () => {
  it("moves the session after its source node is unmounted", () => {
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
    expect(onMove).toHaveBeenCalledWith("session-1", "new-group");
    expect(screen.getByTestId("dnd-context")).toHaveAttribute(
      "data-measuring-strategy",
      "always",
    );
    expect(mockMeasureDroppableContainers).toHaveBeenCalled();
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

describe("DraggableSession", () => {
  it("keeps the drag wrapper out of the tab order and accessibility tree", () => {
    const { container } = render(
      <DraggableSession
        sessionId="session-1"
        groupId="work"
        label="Conversation"
      >
        <button type="button">Conversation</button>
      </DraggableSession>,
    );

    const wrapper = container.firstElementChild;
    expect(wrapper).not.toHaveAttribute("role");
    expect(wrapper).not.toHaveAttribute("tabindex");
    expect(wrapper).not.toHaveAttribute("aria-describedby");

    fireEvent.pointerDown(wrapper!);
    expect(mockPointerDown).toHaveBeenCalledOnce();
  });
});
