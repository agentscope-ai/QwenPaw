import { useState, type ReactNode } from "react";
import { Button, Popover } from "antd";
import { useAutoSave } from "@/hooks/useAutoSave";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import {
  Check,
  Minus,
  Plus,
  Pencil,
  RotateCcw,
  Inbox,
  GripVertical,
  CircleHelp,
  LockKeyhole,
} from "lucide-react";
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
  onToggle,
}: {
  entry: FlatMenuEntry;
  editing: boolean;
  selected: boolean;
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
      <div className={styles.tileBody} data-editing={editing}>
        <button
          type="button"
          className={styles.dragHandle}
          disabled={!editing}
          {...attributes}
          {...listeners}
          aria-label={t("settingsCenter.moveEntry", { name: entry.label })}
        >
          {editing && (
            <GripVertical className={styles.grip} size={16} aria-hidden />
          )}
          <span className={styles.icon}>{entry.icon}</span>
          <span className={styles.label}>{entry.label}</span>
        </button>
        {editing && (
          <button
            type="button"
            className={styles.badge}
            data-press
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
  const toggle = (id: string) => {
    setDraft((current) =>
      current.includes(id)
        ? current.filter((item) => item !== id)
        : [...current, id],
    );
    scheduleSave();
  };
  const { schedule: scheduleSave, flush } = useAutoSave(async () => {
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
  });
  const finish = () => {
    void flush().then((saved) => {
      if (saved) setEditing(false);
    });
  };
  const onDragEnd = ({ active, over }: DragEndEvent) => {
    setActiveId(null);
    if (!over || active.id === over.id) return;
    const id = String(active.id);
    const target = String(over.id);
    scheduleSave();
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
    <div className={styles.page} data-editing={editing}>
      <header className={styles.header}>
        <div>
          <h3>{t("settingsCenter.pages.navigation")}</h3>
          <Popover
            trigger="click"
            content={t("settingsCenter.sidebarEditHelp")}
          >
            <Button
              type="text"
              className={styles.helpButton}
              aria-label={`${t("settingsCenter.pages.navigation")} · ${t(
                "common.help",
              )}`}
              icon={<CircleHelp size={16} />}
            />
          </Popover>
        </div>
      </header>
      <DndContext
        sensors={sensors}
        accessibility={{
          screenReaderInstructions: {
            draggable: t("settingsCenter.sidebarEditHelp"),
          },
          announcements: {
            onDragStart: ({ active }) =>
              t("settingsCenter.moveEntry", {
                name:
                  entries.find((entry) => entry.key === active.id)?.label ??
                  active.id,
              }),
            onDragOver: ({ over }) =>
              over
                ? t("settingsCenter.moveEntry", {
                    name:
                      entries.find((entry) => entry.key === over.id)?.label ??
                      t("settingsCenter.sidebarPreview"),
                  })
                : undefined,
            onDragEnd: () => t("common.done"),
            onDragCancel: () => t("common.cancel"),
          },
        }}
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
            <div className={styles.previewHeader}>
              <span className={styles.previewTitle}>
                {t("settingsCenter.sidebarPreview")}
                <span className={styles.entryCount}>
                  {selectedEntries.length + 1}
                </span>
              </span>
              <div className={styles.actions}>
                {editing ? (
                  <>
                    <Button
                      type="primary"
                      data-press
                      icon={<Check size={15} />}
                      aria-label={t("common.done")}
                      title={t("common.done")}
                      onClick={finish}
                    >
                      {t("common.done")}
                    </Button>
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
                    >
                      {t("common.edit")}
                    </Button>
                  </>
                )}
              </div>
            </div>
            <div className={styles.previewCard}>
              <DropZone id="preview" className={styles.previewDrop}>
                <SortableContext
                  items={selected}
                  strategy={rectSortingStrategy}
                >
                  {selectedEntries.map((entry) => (
                    <EntryTile
                      key={entry.key}
                      entry={entry}
                      selected
                      editing={editing}
                      onToggle={() => toggle(entry.key)}
                    />
                  ))}
                </SortableContext>
                {!selectedEntries.length && (
                  <p className={styles.empty}>{t("settingsCenter.dropHere")}</p>
                )}
                <div
                  className={styles.fixedTile}
                  title={t("settingsCenter.fixedEntry")}
                >
                  <span className={styles.icon}>
                    <Inbox size={22} />
                  </span>
                  <span className={styles.label}>{t("nav.inbox")}</span>
                  <LockKeyhole
                    size={14}
                    aria-label={t("settingsCenter.fixedEntry")}
                  />
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
                              {available.map((entry) => (
                                <EntryTile
                                  key={entry.key}
                                  entry={entry}
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
          dropAnimation={
            reducedMotion
              ? null
              : { duration: 220, easing: "cubic-bezier(.2,.8,.2,1)" }
          }
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
