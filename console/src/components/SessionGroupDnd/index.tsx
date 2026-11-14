import {
  DndContext,
  DragOverlay,
  getScrollableAncestors,
  MeasuringStrategy,
  MouseSensor,
  pointerWithin,
  TouchSensor,
  useDndContext,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
  type CollisionDetection,
} from "@dnd-kit/core";
import { GripVertical } from "lucide-react";
import {
  createContext,
  useCallback,
  useContext,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import styles from "./SessionGroupDnd.module.less";

interface DragData {
  sessionId: string;
  groupId: string;
  label: string;
}

const DragSourceGroupContext = createContext<string | null>(null);

export const sessionGroupCollisionDetection: CollisionDetection = (args) => {
  const pointer = args.pointerCoordinates;
  if (!pointer) return [];
  return pointerWithin(args).filter(({ id }) => {
    const node = args.droppableContainers.find((item) => item.id === id)?.node
      .current;
    if (!node) return false;
    // Virtualized rows may remain mounted beyond the visible scroll viewport.
    return getScrollableAncestors(node).every((ancestor) => {
      const rect = ancestor.getBoundingClientRect();
      return (
        pointer.x >= rect.left &&
        pointer.x <= rect.right &&
        pointer.y >= rect.top &&
        pointer.y <= rect.bottom
      );
    });
  });
};

interface SessionGroupDndProviderProps {
  children: ReactNode;
  onMove: (sessionId: string, groupId: string) => void;
  onDragStateChange: (active: boolean) => void;
}

function DroppableRemeasurer({ active }: { active: boolean }) {
  const { measureDroppableContainers } = useDndContext();

  useLayoutEffect(() => {
    if (active) measureDroppableContainers([]);
  }, [active, measureDroppableContainers]);

  return null;
}

export function SessionGroupDndProvider({
  children,
  onMove,
  onDragStateChange,
}: SessionGroupDndProviderProps) {
  const sensors = useSensors(
    useSensor(MouseSensor, {
      activationConstraint: { delay: 220, tolerance: 6 },
    }),
    useSensor(TouchSensor, {
      activationConstraint: { delay: 300, tolerance: 8 },
    }),
  );
  const [active, setActive] = useState<DragData | null>(null);
  const activeRef = useRef<DragData | null>(null);

  const handleDragStart = useCallback(
    (event: DragStartEvent) => {
      const source = event.active.data.current as DragData;
      activeRef.current = source;
      setActive(source);
      onDragStateChange(true);
    },
    [onDragStateChange],
  );

  const handleDragCancel = useCallback(() => {
    activeRef.current = null;
    setActive(null);
    onDragStateChange(false);
  }, [onDragStateChange]);

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      const source = activeRef.current;
      const groupId = event.over?.data.current?.groupId;
      activeRef.current = null;
      setActive(null);
      onDragStateChange(false);
      if (source && typeof groupId === "string" && groupId !== source.groupId) {
        onMove(source.sessionId, groupId);
      }
    },
    [onDragStateChange, onMove],
  );

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={sessionGroupCollisionDetection}
      measuring={{
        droppable: {
          strategy: MeasuringStrategy.Always,
        },
      }}
      onDragStart={handleDragStart}
      onDragCancel={handleDragCancel}
      onDragEnd={handleDragEnd}
    >
      <DroppableRemeasurer active={active !== null} />
      <DragSourceGroupContext.Provider value={active?.groupId ?? null}>
        {children}
      </DragSourceGroupContext.Provider>
      <DragOverlay>
        {active ? (
          <div className={styles.overlay}>
            <GripVertical size={14} />
            <span>{active.label}</span>
          </div>
        ) : null}
      </DragOverlay>
    </DndContext>
  );
}

interface SessionDropZoneProps {
  id: string;
  groupId: string;
  children: ReactNode;
  style?: CSSProperties;
  className?: string;
}

export function SessionDropZone({
  id,
  groupId,
  children,
  style,
  className = "",
}: SessionDropZoneProps) {
  const sourceGroupId = useContext(DragSourceGroupContext);
  const { isOver, setNodeRef } = useDroppable({
    id,
    data: { groupId },
  });
  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`${className} ${
        isOver && sourceGroupId !== null && sourceGroupId !== groupId
          ? styles.dropActive
          : ""
      }`}
    >
      {children}
    </div>
  );
}

interface DraggableSessionProps {
  sessionId: string;
  groupId: string;
  label: string;
  children: ReactNode;
}

export function DraggableSession({
  sessionId,
  groupId,
  label,
  children,
}: DraggableSessionProps) {
  const { isDragging, listeners, setNodeRef } = useDraggable({
    id: `session:${sessionId}`,
    data: { sessionId, groupId, label } satisfies DragData,
  });
  return (
    <div
      ref={setNodeRef}
      className={`${styles.draggable} ${isDragging ? styles.dragging : ""}`}
      onPointerDownCapture={(event) => {
        if (
          (event.target as HTMLElement).closest(
            "button, input, textarea, [role='menuitem']",
          )
        ) {
          event.stopPropagation();
        }
      }}
      {...listeners}
    >
      {children}
    </div>
  );
}
