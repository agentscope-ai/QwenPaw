import { useTranslation } from "react-i18next";
import React, { createContext, useContext } from "react";
import { GripVertical } from "lucide-react";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import styles from "../index.module.less";

type SortableHandleContextValue = {
  attributes: ReturnType<typeof useSortable>["attributes"];
  listeners: ReturnType<typeof useSortable>["listeners"];
  disabled: boolean;
};

const SortableHandleContext = createContext<SortableHandleContextValue | null>(
  null,
);

interface SortableAgentRowProps
  extends React.HTMLAttributes<HTMLTableRowElement> {
  "data-row-key": string;
}

export function SortableAgentRow({
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
  } = useSortable({
    id: props["data-row-key"],
  });

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
      value={{
        attributes,
        listeners,
        disabled: false,
      }}
    >
      <tr
        {...props}
        ref={setNodeRef}
        className={rowClassName}
        style={sortableStyle}
      >
        {children}
      </tr>
    </SortableHandleContext.Provider>
  );
}

export function DragHandle({ disabled = false }: { disabled?: boolean }) {
  const { t } = useTranslation();
  const context = useContext(SortableHandleContext);
  if (!context) {
    return null;
  }

  const dragBindings = disabled
    ? {}
    : {
        ...context.attributes,
        ...context.listeners,
      };

  return (
    <button
      type="button"
      className={styles.dragHandleButton}
      onClick={(event) => event.stopPropagation()}
      tabIndex={disabled ? -1 : 0}
      aria-label={t("agent.dragHandleTooltip")}
      aria-disabled={disabled}
      {...dragBindings}
    >
      <GripVertical size={16} />
    </button>
  );
}
