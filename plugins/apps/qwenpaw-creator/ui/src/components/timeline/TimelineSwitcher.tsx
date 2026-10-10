import { useCallback, useEffect, useState } from "react";
import { Dropdown, Input, Modal, Tooltip } from "antd";
import {
  Copy,
  Columns2,
  MoreHorizontal,
  Pencil,
  Plus,
  Trash2,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import type { ProjectDocument } from "@/contracts/creator";
import type { ProjectEditOperation } from "@/store/projectSnapshotStore";
import { useTimelineStore } from "@/store/timelineStore";
import {
  createTimelineOperations,
  deleteTimelineOperations,
  duplicateTimelineOperations,
  renameTimelineOperations,
} from "@/api/creator/timelines";

interface TimelineSwitcherProps {
  project: ProjectDocument;
  onPatch: (operations: ProjectEditOperation[]) => Promise<void>;
}

export default function TimelineSwitcher({
  project,
  onPatch,
}: TimelineSwitcherProps) {
  const { t } = useTranslation();
  const { order, items } = project.timelines;
  const activeId = useTimelineStore((s) => s.activeTimelineId);
  const compareId = useTimelineStore((s) => s.compareTimelineId);
  const setActiveTimelineId = useTimelineStore((s) => s.setActiveTimelineId);
  const setCompareTimelineId = useTimelineStore((s) => s.setCompareTimelineId);
  const toggleCompare = useTimelineStore((s) => s.toggleCompare);

  const effectiveActive =
    activeId && items[activeId] ? activeId : order[0] ?? null;

  // Sync timeline store when project timelines change (e.g., new snapshot added)
  useEffect(() => {
    if (activeId && !items[activeId]) {
      setActiveTimelineId(order[0] ?? null);
    }
    if (compareId && !items[compareId]) {
      setCompareTimelineId(null);
    }
  }, [
    items,
    order,
    activeId,
    compareId,
    setActiveTimelineId,
    setCompareTimelineId,
  ]);

  const [renaming, setRenaming] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [createName, setCreateName] = useState("");

  const handleSelect = useCallback(
    (id: string) => {
      setActiveTimelineId(id);
    },
    [setActiveTimelineId],
  );

  const handleCreate = useCallback(async () => {
    const name = createName.trim() || t("timeline.defaultNewName");
    const { operations } = createTimelineOperations(project, name);
    await onPatch(operations);
    setCreateName("");
    setCreateOpen(false);
  }, [createName, project, onPatch, t]);

  const handleRename = useCallback(
    async (id: string) => {
      const name = renameValue.trim();
      if (!name) return;
      await onPatch(renameTimelineOperations(id, name));
      setRenaming(null);
    },
    [renameValue, onPatch],
  );

  const handleDuplicate = useCallback(
    async (id: string) => {
      const source = items[id];
      const name = source?.name
        ? `${source.name} (${t("timeline.copySuffix")})`
        : t("timeline.defaultNewName");
      const { operations } = duplicateTimelineOperations(project, id, name);
      await onPatch(operations);
    },
    [items, project, onPatch, t],
  );

  const handleDelete = useCallback(
    async (id: string) => {
      if (order.length <= 1) return;
      Modal.confirm({
        title: t("timeline.deleteConfirmTitle"),
        content: t("timeline.deleteConfirmContent", {
          name: items[id]?.name || id,
        }),
        okText: t("common.delete"),
        okButtonProps: { danger: true },
        cancelText: t("common.cancel"),
        onOk: async () => {
          const ops = deleteTimelineOperations(project, id);
          await onPatch(ops);
          if (effectiveActive === id) {
            const remaining = order.filter((tid) => tid !== id);
            setActiveTimelineId(remaining[0] ?? null);
          }
        },
      });
    },
    [order, items, project, effectiveActive, onPatch, setActiveTimelineId, t],
  );

  if (order.length === 0) return null;

  return (
    <div className="flex items-center gap-1 border-b border-[var(--color-border)] bg-[var(--color-bg-primary)]/40 px-4 py-1.5">
      <div className="flex items-center gap-1 overflow-x-auto">
        {order.map((tid) => {
          const timeline = items[tid];
          if (!timeline) return null;
          const isActive = tid === effectiveActive;
          const isCompare = tid === compareId;
          const label = timeline.name || tid;

          return (
            <div key={tid} className="group relative flex items-center">
              <button
                type="button"
                onClick={() => handleSelect(tid)}
                className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1 text-xs font-medium transition ${
                  isActive
                    ? "bg-[var(--color-accent-soft)] text-[var(--color-accent)]"
                    : "text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)] hover:text-[var(--color-text-primary)]"
                } ${isCompare ? "ring-1 ring-[var(--color-accent)]/30" : ""}`}
              >
                {isCompare && (
                  <Columns2 className="h-3 w-3 text-[var(--color-accent)]" />
                )}
                <span className="max-w-[120px] truncate">{label}</span>
                <span className="text-[10px] opacity-50">
                  {Object.keys(timeline.elements_by_id).length}
                </span>
              </button>
              <Dropdown
                trigger={["click"]}
                menu={{
                  items: [
                    {
                      key: "rename",
                      label: t("timeline.rename"),
                      icon: <Pencil className="h-3.5 w-3.5" />,
                      onClick: () => {
                        setRenaming(tid);
                        setRenameValue(timeline.name || "");
                      },
                    },
                    {
                      key: "duplicate",
                      label: t("timeline.duplicate"),
                      icon: <Copy className="h-3.5 w-3.5" />,
                      onClick: () => void handleDuplicate(tid),
                    },
                    {
                      key: "compare",
                      label: isCompare
                        ? t("timeline.exitCompare")
                        : t("timeline.compareAB"),
                      icon: <Columns2 className="h-3.5 w-3.5" />,
                      disabled: tid === effectiveActive,
                      onClick: () => toggleCompare(tid),
                    },
                    { type: "divider" },
                    {
                      key: "delete",
                      label: t("timeline.delete"),
                      icon: <Trash2 className="h-3.5 w-3.5" />,
                      danger: true,
                      disabled: order.length <= 1,
                      onClick: () => void handleDelete(tid),
                    },
                  ],
                }}
              >
                <button
                  type="button"
                  className="ml-0.5 inline-flex items-center rounded p-0.5 text-[var(--color-text-tertiary)] opacity-0 transition hover:bg-[var(--color-bg-secondary)] hover:text-[var(--color-text-primary)] group-hover:opacity-100"
                  onClick={(e) => e.stopPropagation()}
                >
                  <MoreHorizontal className="h-3 w-3" />
                </button>
              </Dropdown>
            </div>
          );
        })}
      </div>

      <Tooltip title={t("timeline.addTimeline")}>
        <button
          type="button"
          onClick={() => setCreateOpen(true)}
          className="ml-1 inline-flex items-center rounded-md p-1 text-[var(--color-text-tertiary)] transition hover:bg-[var(--color-bg-secondary)] hover:text-[var(--color-text-primary)]"
        >
          <Plus className="h-3.5 w-3.5" />
        </button>
      </Tooltip>

      <Modal
        title={t("timeline.createTitle")}
        open={createOpen}
        onOk={() => void handleCreate()}
        onCancel={() => {
          setCreateOpen(false);
          setCreateName("");
        }}
        okText={t("common.create")}
        cancelText={t("common.cancel")}
      >
        <Input
          autoFocus
          value={createName}
          onChange={(e) => setCreateName(e.target.value)}
          placeholder={t("timeline.namePlaceholder")}
          onPressEnter={() => void handleCreate()}
        />
      </Modal>

      <Modal
        title={t("timeline.renameTitle")}
        open={renaming !== null}
        onOk={() => renaming && void handleRename(renaming)}
        onCancel={() => setRenaming(null)}
        okText={t("common.save")}
        cancelText={t("common.cancel")}
      >
        <Input
          autoFocus
          value={renameValue}
          onChange={(e) => setRenameValue(e.target.value)}
          placeholder={t("timeline.namePlaceholder")}
          onPressEnter={() => renaming && void handleRename(renaming)}
        />
      </Modal>
    </div>
  );
}
