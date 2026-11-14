import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import {
  DraggableSession,
  SessionGroupDndProvider,
  sessionGroupCollisionDetection,
} from "./index";

const { mockMeasureDroppableContainers, mockPointerDown } = vi.hoisted(() => ({
  mockMeasureDroppableContainers: vi.fn(),
  mockPointerDown: vi.fn(),
}));

vi.mock("@dnd-kit/core", async (original) => ({
  ...(await original<typeof import("@dnd-kit/core")>()),
  DndContext: ({
    children,
    onDragStart,
    onDragEnd,
    onDragOver,
    onDragCancel,
    measuring,
    collisionDetection,
  }: {
    children: ReactNode;
    onDragStart: (event: unknown) => void;
    onDragEnd: (event: unknown) => void;
    onDragOver: (event: unknown) => void;
    onDragCancel: () => void;
    measuring?: { droppable?: { strategy?: string } };
    collisionDetection?: unknown;
  }) => (
    <div
      data-testid="dnd-context"
      data-measuring-strategy={measuring?.droppable?.strategy}
      data-pointer-targets={
        collisionDetection === sessionGroupCollisionDetection
      }
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
      <button onClick={() => onDragEnd({ over: null })}>drop outside</button>
      <button
        onClick={() =>
          onDragEnd({ over: { data: { current: { groupId: "work" } } } })
        }
      >
        drop original group
      </button>
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
    transform: { x: 40, y: 80, scaleX: 1, scaleY: 1 },
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
    expect(screen.getByTestId("dnd-context")).toHaveAttribute(
      "data-pointer-targets",
      "true",
    );
  });

  it.each(["drop outside", "drop original group", "cancel dragging"])(
    "does not move a session on %s, even after hovering another group",
    (action) => {
      const onMove = vi.fn();
      render(
        <SessionGroupDndProvider onMove={onMove} onDragStateChange={vi.fn()}>
          <span>session list</span>
        </SessionGroupDndProvider>,
      );
      fireEvent.click(screen.getByText("start dragging"));
      fireEvent.click(screen.getByText("hover target"));
      fireEvent.click(screen.getByText(action));
      expect(onMove).not.toHaveBeenCalled();
    },
  );

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
    expect(wrapper).not.toHaveAttribute("style");

    fireEvent.pointerDown(wrapper!);
    expect(mockPointerDown).toHaveBeenCalledOnce();
  });
});

describe("sessionGroupCollisionDetection", () => {
  it("accepts visible pointer targets and rejects clipped rows and overlay-only overlaps", () => {
    const viewport = document.createElement("div");
    viewport.style.overflowY = "auto";
    const row = document.createElement("div");
    viewport.appendChild(row);
    document.body.appendChild(viewport);
    vi.spyOn(viewport, "getBoundingClientRect").mockReturnValue(
      new DOMRect(0, 0, 100, 100),
    );
    const rowRect = new DOMRect(0, 90, 100, 40);
    const args = {
      active: {
        id: "session-1",
        data: { current: {} },
        rect: { current: { initial: rowRect, translated: rowRect } },
      },
      collisionRect: rowRect,
      droppableRects: new Map([["target", rowRect]]),
      droppableContainers: [
        {
          id: "target",
          key: "target",
          disabled: false,
          node: { current: row },
          rect: { current: rowRect },
          data: { current: { groupId: "work" } },
        },
      ],
      pointerCoordinates: { x: 50, y: 95 },
    } as Parameters<typeof sessionGroupCollisionDetection>[0];
    try {
      expect(
        sessionGroupCollisionDetection(args).map((item) => item.id),
      ).toEqual(["target"]);
      expect(
        sessionGroupCollisionDetection({
          ...args,
          pointerCoordinates: { x: 50, y: 110 },
        }),
      ).toEqual([]);
      expect(
        sessionGroupCollisionDetection({
          ...args,
          pointerCoordinates: { x: 110, y: 95 },
        }),
      ).toEqual([]);
      expect(
        sessionGroupCollisionDetection({ ...args, pointerCoordinates: null }),
      ).toEqual([]);
    } finally {
      viewport.remove();
    }
  });
});
