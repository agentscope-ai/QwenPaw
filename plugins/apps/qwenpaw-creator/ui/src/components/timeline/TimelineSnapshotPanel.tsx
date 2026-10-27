import { useMemo, useState } from "react";
import { Input, message, Modal, Popover } from "antd";
import { Camera, Eye, History, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { ProjectDocument, TimelineDocument } from "@/contracts/creator";
import type { ProjectEditOperation } from "@/store/projectSnapshotStore";
import { useTimelineStore } from "@/store/timelineStore";
import {
  createSnapshotOperations,
  deleteTimelineOperations,
  listTimelineSnapshots,
  restoreSnapshotOperations,
  snapshotMatchesTimeline,
} from "@/api/creator/timelines";

/** "快照 · name · 2026-09-03 14:22" → ["name 的部分", "时间部分"] */
function splitSnapshotName(name: string): [string, string] {
  const match = /^(.*?)\s*·\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2})$/.exec(name);
  if (match) return [match[1].replace(/^快照\s*·\s*/, ""), match[2]];
  return [name, ""];
}

/** Internal ids like "timeline:main" must never render as a user-facing
    snapshot title (legacy data predates the friendly-name backend fix). */
function isInternalTimelineId(title: string): boolean {
  return /^(snapshot:)?timeline:/.test(title.trim());
}

function nowStamp(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(
    2,
    "0",
  )}-${String(now.getDate()).padStart(2, "0")} ${String(
    now.getHours(),
  ).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
}

/**
 * 历史快照 popover (design 84:039752): entry pill on the transport row; the
 * panel lists the current version plus this timeline's snapshots. Clicking a
 * row only selects it (radio); the eye toggle on the selected row opens the
 * A/B compare preview; 应用快照 first backs up the current state and then
 * restores the selected snapshot onto the base timeline; the trash icon on
 * the selected row deletes that snapshot; 创建快照 freezes the current state
 * under a name.
 */
export default function TimelineSnapshotPanel({
  project,
  timeline,
  onPatch,
}: {
  project: ProjectDocument;
  timeline: TimelineDocument;
  onPatch: (operations: ProjectEditOperation[]) => Promise<void>;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [createName, setCreateName] = useState("");
  const [busy, setBusy] = useState(false);
  // Store-held selection: compare mode and background project polls both
  // remount this panel, and a component-local pick would be wiped.
  const localSelected = useTimelineStore((s) => s.snapshotSelectedId);
  const setLocalSelected = useTimelineStore((s) => s.setSnapshotSelectedId);
  const compareId = useTimelineStore((s) => s.compareTimelineId);
  const setCompareTimelineId = useTimelineStore((s) => s.setCompareTimelineId);
  const snapshots = listTimelineSnapshots(project, timeline.timeline_id);
  const isSnapshot = (id: string | null): id is string =>
    !!id && snapshots.some((s) => s.timeline_id === id);
  const selected = isSnapshot(localSelected)
    ? localSelected
    : isSnapshot(compareId)
    ? compareId
    : null;
  const previewing = isSnapshot(compareId) ? compareId : null;
  // Which snapshot the live content currently equals (i.e. the applied one);
  // derived by content so a later manual edit clears the badge naturally.
  const matchedId = useMemo(() => {
    if (!open) return null;
    return (
      snapshots.find((snapshot) =>
        snapshotMatchesTimeline(project, snapshot.timeline_id),
      )?.timeline_id ?? null
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, project, timeline.timeline_id]);

  const snapshotTitle = (snapshot: TimelineDocument): [string, string] => {
    const [title, time] = splitSnapshotName(snapshot.name || "");
    if (!title || isInternalTimelineId(title))
      return [t("timeline.snapshotAutoName"), time];
    return [title, time];
  };

  const applySnapshot = () => {
    if (!selected) return;
    const [label] = snapshotTitle(project.timelines.items[selected]);
    Modal.confirm({
      title: t("timeline.snapshotApplyTitle"),
      content: t("timeline.snapshotApplyDesc", { name: label }),
      okText: t("timeline.snapshotApply"),
      cancelText: t("common.cancel"),
      onOk: async () => {
        // Back up the current state first so applying is always reversible.
        const operations = [
          ...createSnapshotOperations(
            project,
            timeline.timeline_id,
            `${t("timeline.snapshotPreApplyBackup")} · ${nowStamp()}`,
          ),
          ...restoreSnapshotOperations(project, selected),
        ];
        if (!operations.length) return;
        setBusy(true);
        try {
          await onPatch(operations);
          setLocalSelected(null);
          setCompareTimelineId(null);
          message.success(t("timeline.snapshotApplied"));
          setOpen(false);
        } catch (error) {
          message.error((error as Error).message);
        } finally {
          setBusy(false);
        }
      },
    });
  };

  const deleteSnapshot = (snapshotId: string) => {
    const [label] = snapshotTitle(project.timelines.items[snapshotId]);
    Modal.confirm({
      title: t("timeline.snapshotDeleteTitle"),
      content: t("timeline.snapshotDeleteDesc", { name: label }),
      okText: t("timeline.snapshotDelete"),
      okButtonProps: { danger: true },
      cancelText: t("common.cancel"),
      onOk: async () => {
        const operations = deleteTimelineOperations(project, snapshotId);
        if (!operations.length) return;
        setBusy(true);
        try {
          await onPatch(operations);
          setLocalSelected(null);
          setCompareTimelineId(null);
          message.success(t("timeline.snapshotDeleted"));
        } catch (error) {
          message.error((error as Error).message);
        } finally {
          setBusy(false);
        }
      },
    });
  };

  const createSnapshot = async () => {
    const name = createName.trim() || t("timeline.snapshotDefaultName");
    const operations = createSnapshotOperations(
      project,
      timeline.timeline_id,
      `${name} · ${nowStamp()}`,
    );
    if (!operations.length) return;
    setBusy(true);
    try {
      await onPatch(operations);
      message.success(t("timeline.snapshotCreated"));
      setCreateOpen(false);
      setCreateName("");
    } catch (error) {
      message.error((error as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const entryRow = (
    key: string,
    title: string,
    time: string,
    trailing: React.ReactNode,
    highlighted: boolean,
    onClick?: () => void,
  ) => (
    <button
      key={key}
      type="button"
      data-snapshot-row={key}
      onClick={onClick}
      disabled={!onClick}
      className={`flex w-full items-center gap-3 rounded-md border px-3 py-2 text-left transition-colors ${
        highlighted
          ? "border-[#FFD7AC] bg-[#FFF3E6] dark:border-[var(--color-accent)]/40 dark:bg-[var(--color-accent-soft)]"
          : "border-transparent hover:bg-[var(--color-bg-secondary)]"
      } ${onClick ? "" : "cursor-default"}`}
    >
      <Camera className="h-5 w-5 shrink-0 text-[var(--color-text-secondary)]" />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium text-[var(--color-text-primary)]">
          {title}
        </span>
        {time && (
          <span className="mt-0.5 block text-xs text-[var(--color-text-tertiary)]">
            {time}
          </span>
        )}
      </span>
      {trailing}
    </button>
  );

  const panel = (
    <div className="w-[264px]" data-snapshot-panel>
      <div className="flex items-baseline gap-2 px-1 pb-2">
        <span className="text-sm font-medium text-[var(--color-text-primary)]">
          {t("timeline.snapshotHistory")}
        </span>
        <span className="text-xs text-[var(--color-text-tertiary)]">
          {t("timeline.snapshotPreviewHint")}
        </span>
      </div>
      <div className="max-h-[300px] space-y-1 overflow-y-auto">
        {entryRow(
          timeline.timeline_id,
          timeline.name || timeline.title || t("timeline.snapshotCurrent"),
          matchedId
            ? t("timeline.snapshotCurrentMatches", {
                name: snapshotTitle(project.timelines.items[matchedId])[0],
              })
            : "",
          <span className="shrink-0 rounded border border-[var(--color-accent)]/40 bg-[var(--color-accent-soft)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--color-accent)]">
            {t("timeline.snapshotCurrent")}
          </span>,
          selected === null,
          () => {
            setLocalSelected(null);
            setCompareTimelineId(null);
          },
        )}
        {snapshots.map((snapshot) => {
          const [title, time] = snapshotTitle(snapshot);
          const picked = selected === snapshot.timeline_id;
          const inPreview = previewing === snapshot.timeline_id;
          const applied = matchedId === snapshot.timeline_id;
          return entryRow(
            snapshot.timeline_id,
            title,
            time,
            <span className="flex shrink-0 items-center gap-1.5">
              {applied && (
                <span
                  data-snapshot-applied={snapshot.timeline_id}
                  className="rounded border border-[var(--color-accent)]/40 bg-[var(--color-accent-soft)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--color-accent)]"
                >
                  {t("timeline.snapshotInUse")}
                </span>
              )}
              {picked && (
                <>
                  <span
                    role="button"
                    tabIndex={0}
                    data-snapshot-preview={snapshot.timeline_id}
                    title={
                      inPreview
                        ? t("timeline.snapshotExitCompare")
                        : t("timeline.snapshotPreview")
                    }
                    onClick={(event) => {
                      event.stopPropagation();
                      setCompareTimelineId(
                        inPreview ? null : snapshot.timeline_id,
                      );
                    }}
                    onKeyDown={(event) => {
                      if (event.key !== "Enter" && event.key !== " ") return;
                      event.preventDefault();
                      event.stopPropagation();
                      setCompareTimelineId(
                        inPreview ? null : snapshot.timeline_id,
                      );
                    }}
                    className={`flex h-5 w-5 items-center justify-center rounded ${
                      inPreview
                        ? "bg-[var(--color-accent)] text-white"
                        : "text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)]"
                    }`}
                  >
                    <Eye className="h-3.5 w-3.5" />
                  </span>
                  <span
                    role="button"
                    tabIndex={0}
                    data-snapshot-delete={snapshot.timeline_id}
                    title={t("timeline.snapshotDelete")}
                    onClick={(event) => {
                      event.stopPropagation();
                      deleteSnapshot(snapshot.timeline_id);
                    }}
                    onKeyDown={(event) => {
                      if (event.key !== "Enter" && event.key !== " ") return;
                      event.preventDefault();
                      event.stopPropagation();
                      deleteSnapshot(snapshot.timeline_id);
                    }}
                    className="flex h-5 w-5 items-center justify-center rounded text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)] hover:text-[var(--color-danger)]"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </span>
                </>
              )}
              <span
                aria-hidden="true"
                className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full border ${
                  picked
                    ? "border-[var(--color-accent)]"
                    : "border-[var(--color-border-strong)]"
                }`}
              >
                {picked && (
                  <span className="h-2.5 w-2.5 rounded-full bg-[var(--color-accent)]" />
                )}
              </span>
            </span>,
            picked,
            () => {
              if (picked) {
                setLocalSelected(null);
                setCompareTimelineId(null);
              } else {
                setLocalSelected(snapshot.timeline_id);
              }
            },
          );
        })}
      </div>
      <div className="mt-3 flex justify-end gap-3 border-t border-[var(--color-border)] pt-3">
        <button
          type="button"
          data-snapshot-apply
          disabled={!selected || busy}
          onClick={applySnapshot}
          className="rounded-md border border-[var(--color-border)] px-3 py-1.5 text-xs font-medium text-[var(--color-text-primary)] transition-colors hover:border-[var(--color-border-strong)] disabled:cursor-not-allowed disabled:opacity-40"
        >
          {t("timeline.snapshotApply")}
        </button>
        <button
          type="button"
          data-snapshot-create
          disabled={busy}
          onClick={() => setCreateOpen(true)}
          className="rounded-md border border-[var(--color-border)] px-3 py-1.5 text-xs font-medium text-[var(--color-text-primary)] transition-colors hover:border-[var(--color-border-strong)] disabled:cursor-not-allowed disabled:opacity-40"
        >
          {t("timeline.snapshotCreate")}
        </button>
      </div>
    </div>
  );

  return (
    <>
      <Popover
        open={open}
        onOpenChange={setOpen}
        trigger="click"
        placement="topRight"
        content={panel}
      >
        <button
          type="button"
          data-snapshot-entry
          className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium text-[var(--color-text-primary)] transition-colors ${
            open
              ? "bg-[var(--color-bg-secondary)]"
              : "hover:bg-[var(--color-bg-secondary)]"
          }`}
        >
          <History className="h-3.5 w-3.5" />
          {t("timeline.snapshotHistory")}
        </button>
      </Popover>
      <Modal
        open={createOpen}
        title={t("timeline.snapshotCreateTitle")}
        okText={t("timeline.snapshotCreate")}
        cancelText={t("common.cancel")}
        confirmLoading={busy}
        onOk={() => void createSnapshot()}
        onCancel={() => setCreateOpen(false)}
        destroyOnHidden
      >
        <Input
          value={createName}
          onChange={(event) => setCreateName(event.target.value)}
          placeholder={t("timeline.snapshotNamePlaceholder")}
          maxLength={40}
        />
      </Modal>
    </>
  );
}
