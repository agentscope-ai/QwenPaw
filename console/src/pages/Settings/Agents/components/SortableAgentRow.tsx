import React, { createContext, useContext } from "react";
import { GripVertical } from "lucide-react";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { TableRow } from "@/components/ui/table";
import styles from "../index.module.less";

type SortableHandleContextValue = {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  attributes: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  listeners: any;
  disabled: boolean;
};

const SortableHandleContext = createContext<SortableHandleContextValue | null>(
  null,
);

interface SortableAgentRowProps
  extends React.HTMLAttributes<HTMLTableRowElement> {
  id: string;
  children?: React.ReactNode;
}

export function SortableAgentRow({
  id,
  children,
  className,
  style,
  ...props
}: SortableAgentRowProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id });

  const sortableStyle: React.CSSProperties = {
    ...style,
    transform: CSS.Transform.toString(transform),
    transition,
  };

  const rowClassName = [className, isDragging ? styles.sortableRowDragging : ""]
    .filter(Boolean)
    .join(" ");

  return (
    <SortableHandleContext.Provider
      value={{ attributes, listeners, disabled: false }}
    >
      <TableRow
        {...props}
        ref={setNodeRef}
        className={rowClassName}
        style={sortableStyle}
      >
        {children}
      </TableRow>
    </SortableHandleContext.Provider>
  );
}

export function DragHandle({ disabled = false }: { disabled?: boolean }) {
  const context = useContext(SortableHandleContext);
  if (!context) return null;

  const dragBindings = disabled
    ? {}
    : { ...context.attributes, ...context.listeners };

  return (
    <button
      type="button"
      className={styles.dragHandleButton}
      onClick={(e) => e.stopPropagation()}
      tabIndex={disabled ? -1 : 0}
      aria-disabled={disabled}
      {...dragBindings}
    >
      <GripVertical size={14} />
    </button>
  );
}
