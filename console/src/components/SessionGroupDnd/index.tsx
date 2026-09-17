import {
  DndContext,
  DragOverlay,
  MeasuringStrategy,
  MouseSensor,
  TouchSensor,
  useDndContext,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragOverEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { GripVertical } from "lucide-react";
import {
  createContext,
  useCallback,
  useContext,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import { CSS } from "@dnd-kit/utilities";
import styles from "./SessionGroupDnd.module.less";

interface DragData {
  sessionId: string;
  groupId: string;
  label: string;
}

const DragStateContext = createContext<{
  active: boolean;
  overGroupId: string | null;
}>({ active: false, overGroupId: null });

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
  const [overGroupId, setOverGroupId] = useState<string | null>(null);

  const handleDragStart = useCallback(
    (event: DragStartEvent) => {
      const source = event.active.data.current as DragData;
      activeRef.current = source;
      setActive(source);
      setOverGroupId(null);
      onDragStateChange(true);
    },
    [onDragStateChange],
  );

  const handleDragOver = useCallback((event: DragOverEvent) => {
    const groupId = event.over?.data.current?.groupId;
    if (typeof groupId === "string") {
      setOverGroupId(groupId);
    } else {
      setOverGroupId(null);
    }
  }, []);

  const handleDragCancel = useCallback(() => {
    activeRef.current = null;
    setActive(null);
    setOverGroupId(null);
    onDragStateChange(false);
  }, [onDragStateChange]);

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      const source = activeRef.current;
      const groupId = event.over?.data.current?.groupId;
      activeRef.current = null;
      setActive(null);
      setOverGroupId(null);
      onDragStateChange(false);
      if (source && typeof groupId === "string" && groupId !== source.groupId) {
        onMove(source.sessionId, groupId);
      }
    },
    [onDragStateChange, onMove],
  );
  const dragState = useMemo(
    () => ({ active: active !== null, overGroupId }),
    [active, overGroupId],
  );

  return (
    <DndContext
      sensors={sensors}
      measuring={{
        droppable: {
          strategy: MeasuringStrategy.Always,
        },
      }}
      onDragStart={handleDragStart}
      onDragOver={handleDragOver}
      onDragCancel={handleDragCancel}
      onDragEnd={handleDragEnd}
    >
      <DroppableRemeasurer active={active !== null} />
      <DragStateContext.Provider value={dragState}>
        {children}
      </DragStateContext.Provider>
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
  const { active, overGroupId } = useContext(DragStateContext);
  const { setNodeRef } = useDroppable({
    id,
    data: { groupId },
  });
  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`${className} ${
        active && overGroupId === groupId ? styles.dropActive : ""
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
  const { attributes, isDragging, listeners, setNodeRef, transform } =
    useDraggable({
      id: `session:${sessionId}`,
      data: { sessionId, groupId, label } satisfies DragData,
    });
  return (
    <div
      ref={setNodeRef}
      className={`${styles.draggable} ${isDragging ? styles.dragging : ""}`}
      style={{ transform: CSS.Translate.toString(transform) }}
      onPointerDownCapture={(event) => {
        if (
          (event.target as HTMLElement).closest(
            "button, input, textarea, [role='menuitem']",
          )
        ) {
          event.stopPropagation();
        }
      }}
      {...attributes}
      {...listeners}
    >
      {children}
    </div>
  );
}
