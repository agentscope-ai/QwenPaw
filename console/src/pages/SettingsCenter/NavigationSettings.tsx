import { useState, type ReactNode } from "react";
import { Button } from "antd";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { Check, Minus, Plus, Pencil, RotateCcw, Inbox, X } from "lucide-react";
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  KeyboardSensor,
  useSensor,
  useSensors,
  useDroppable,
  closestCenter,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  useSortable,
  arrayMove,
  rectSortingStrategy,
  sortableKeyboardCoordinates,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { useTranslation } from "react-i18next";
import { useSidebarStore } from "@/stores/sidebarStore";
import { orderSidebarEntries } from "@/layouts/registry/sidebarEntries";
import type { FlatMenuEntry } from "@/layouts/registry/adapter";
import { useSidebarEntryGroups } from "./useSidebarEntryGroups";
import styles from "./NavigationSettings.module.less";

function DropZone({
  id,
  children,
  className,
}: {
  id: string;
  children: ReactNode;
  className: string;
}) {
  const { setNodeRef, isOver } = useDroppable({ id });
  return (
    <div ref={setNodeRef} className={className} data-over={isOver}>
      {children}
    </div>
  );
}

function EntryTile({
  entry,
  editing,
  selected,
  index,
  onToggle,
}: {
  entry: FlatMenuEntry;
  editing: boolean;
  selected: boolean;
  index: number;
  onToggle: () => void;
}) {
  const { t } = useTranslation();
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: entry.key, disabled: !editing });
  return (
    <div
      ref={setNodeRef}
      className={styles.tile}
      data-dragging={isDragging}
      style={{ transform: CSS.Transform.toString(transform), transition }}
    >
      <div
        className={styles.tileBody}
        data-editing={editing}
        style={{ animationDelay: `${(index % 3) * -0.07}s` }}
      >
        <button
          type="button"
          className={styles.dragHandle}
          disabled={!editing}
          {...attributes}
          {...listeners}
          aria-label={t("settingsCenter.moveEntry", { name: entry.label })}
        >
          <span className={styles.icon}>{entry.icon}</span>
          <span className={styles.label}>{entry.label}</span>
        </button>
        {editing && (
          <button
            type="button"
            className={styles.badge}
            data-selected={selected}
            onClick={onToggle}
            aria-label={t(
              selected
                ? "settingsCenter.removeEntry"
                : "settingsCenter.addEntry",
              { name: entry.label },
            )}
          >
            {selected ? <Minus size={12} /> : <Plus size={12} />}
          </button>
        )}
      </div>
    </div>
  );
}

export default function NavigationSettings() {
  const { t } = useTranslation();
  const reducedMotion = useReducedMotion();
  const { work, global, plugins } = useSidebarEntryGroups();
  const {
    focusItemIds,
    hiddenPluginItemIds,
    setFocusItemIds,
    setSidebarItemsVisible,
    resetFocusItemIds,
  } = useSidebarStore();
  const entries = [...work, ...global, ...plugins];
  const visible = orderSidebarEntries(
    entries.filter((entry) =>
      entry.key.startsWith("core.")
        ? focusItemIds.includes(entry.key)
        : !hiddenPluginItemIds.includes(entry.key),
    ),
    focusItemIds,
  ).map((entry) => entry.key);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<string[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const selected = editing ? draft : visible;
  const selectedEntries = selected.flatMap((id) => {
    const entry = entries.find((item) => item.key === id);
    return entry ? [entry] : [];
  });
  const active = entries.find((entry) => entry.key === activeId);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );
  const toggle = (id: string) =>
    setDraft((current) =>
      current.includes(id)
        ? current.filter((item) => item !== id)
        : [...current, id],
    );
  const finish = () => {
    const editableIds = new Set(entries.map((entry) => entry.key));
    setFocusItemIds([
      ...draft,
      ...focusItemIds.filter((id) => !editableIds.has(id)),
    ]);
    setSidebarItemsVisible(
      plugins
        .filter((entry) => !draft.includes(entry.key))
        .map((entry) => entry.key),
      false,
    );
    setSidebarItemsVisible(
      plugins
        .filter((entry) => draft.includes(entry.key))
        .map((entry) => entry.key),
      true,
    );
    setEditing(false);
  };
  const onDragEnd = ({ active, over }: DragEndEvent) => {
    setActiveId(null);
    if (!over || active.id === over.id) return;
    const id = String(active.id);
    const target = String(over.id);
    setDraft((current) => {
      const from = current.indexOf(id);
      const to = current.indexOf(target);
      if (target === "library" || (to === -1 && target !== "preview"))
        return current.filter((item) => item !== id);
      if (from === -1) {
        const next = [...current];
        next.splice(to < 0 ? next.length : to, 0, id);
        return next;
      }
      return arrayMove(current, from, to < 0 ? current.length - 1 : to);
    });
  };
  const groups = [
    {
      key: "work",
      label: t("settingsCenter.sidebarGroups.agentConfiguration"),
      entries: work,
    },
    {
      key: "global",
      label: t("settingsCenter.sidebarGroups.global"),
      entries: global,
    },
    {
      key: "plugins",
      label: t("settingsCenter.sidebarGroups.plugins"),
      entries: plugins,
    },
  ];
  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <h3>{t("settingsCenter.pages.navigation")}</h3>
        </div>
      </header>
      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragStart={({ active }) => setActiveId(String(active.id))}
        onDragEnd={onDragEnd}
        onDragCancel={() => setActiveId(null)}
      >
        <motion.div
          layout
          className={styles.workspace}
          data-editing={editing}
          transition={
            reducedMotion
              ? { duration: 0 }
              : { type: "spring", stiffness: 320, damping: 32 }
          }
        >
          <section
            className={styles.preview}
            aria-label={t("settingsCenter.sidebarPreview")}
          >
            <div className={styles.actions}>
              {editing ? (
                <>
                  <Button
                    type="text"
                    aria-label={t("common.cancel")}
                    title={t("common.cancel")}
                    icon={<X size={16} />}
                    onClick={() => setEditing(false)}
                  />
                  <Button
                    type="primary"
                    data-press
                    icon={<Check size={15} />}
                    aria-label={t("common.done")}
                    title={t("common.done")}
                    onClick={finish}
                  />
                </>
              ) : (
                <>
                  <Button
                    type="text"
                    aria-label={t("common.reset")}
                    title={t("common.reset")}
                    icon={<RotateCcw size={16} />}
                    onClick={resetFocusItemIds}
                  />
                  <Button
                    type="primary"
                    data-press
                    icon={<Pencil size={15} />}
                    aria-label={t("common.edit")}
                    title={t("common.edit")}
                    onClick={() => {
                      setDraft(visible);
                      setEditing(true);
                    }}
                  />
                </>
              )}
            </div>
            <div className={styles.previewCard}>
              <DropZone id="preview" className={styles.previewDrop}>
                <SortableContext
                  items={selected}
                  strategy={rectSortingStrategy}
                >
                  {selectedEntries.map((entry, index) => (
                    <EntryTile
                      key={entry.key}
                      entry={entry}
                      index={index}
                      selected
                      editing={editing}
                      onToggle={() => toggle(entry.key)}
                    />
                  ))}
                </SortableContext>
                {!selectedEntries.length && (
                  <p className={styles.empty}>{t("settingsCenter.dropHere")}</p>
                )}
                <div className={styles.fixedTile}>
                  <span className={styles.icon}>
                    <Inbox size={22} />
                  </span>
                  <span className={styles.label}>{t("nav.inbox")}</span>
                </div>
              </DropZone>
            </div>
          </section>
          <AnimatePresence initial={false}>
            {editing && (
              <motion.div
                className={styles.libraryReveal}
                initial={{ opacity: 0, height: 0, y: reducedMotion ? 0 : -12 }}
                animate={{ opacity: 1, height: "auto", y: 0 }}
                exit={{ opacity: 0, height: 0, y: reducedMotion ? 0 : -8 }}
                transition={
                  reducedMotion
                    ? { duration: 0 }
                    : { type: "spring", stiffness: 360, damping: 34 }
                }
              >
                <DropZone id="library" className={styles.library}>
                  <h3>{t("settingsCenter.availableEntries")}</h3>
                  {groups.map((group) => {
                    const available = group.entries.filter(
                      (entry) => !selected.includes(entry.key),
                    );
                    return (
                      group.entries.length > 0 && (
                        <section key={group.key}>
                          <h3 className={styles.groupTitle}>{group.label}</h3>
                          <div className={styles.libraryGrid}>
                            <SortableContext
                              items={available.map((entry) => entry.key)}
                              strategy={rectSortingStrategy}
                            >
                              {available.map((entry, index) => (
                                <EntryTile
                                  key={entry.key}
                                  entry={entry}
                                  index={index}
                                  selected={false}
                                  editing={editing}
                                  onToggle={() => toggle(entry.key)}
                                />
                              ))}
                            </SortableContext>
                            {!available.length && (
                              <span className={styles.empty}>
                                {t("settingsCenter.allAdded")}
                              </span>
                            )}
                          </div>
                        </section>
                      )
                    );
                  })}
                </DropZone>
              </motion.div>
            )}
          </AnimatePresence>
        </motion.div>
        <DragOverlay
          dropAnimation={{ duration: 220, easing: "cubic-bezier(.2,.8,.2,1)" }}
        >
          {active && (
            <div className={styles.dragPreview}>
              <span className={styles.icon}>{active.icon}</span>
              <span>{active.label}</span>
            </div>
          )}
        </DragOverlay>
      </DndContext>
    </div>
  );
}
