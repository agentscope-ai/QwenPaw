import { useEffect, useMemo, useState } from "react";
import { Button, Modal } from "antd";
import { Check, Image as ImageIcon } from "lucide-react";
import { useTranslation } from "react-i18next";

export type PickerKind = "character" | "scene" | "prop" | "material";

export interface PickerCandidate {
  id: string;
  kind: PickerKind;
  name: string;
  thumbUrl: string | null;
}

/**
 * 缩略版资产库：browse every addable asset of the project in one grid,
 * toggle-pick cards, and confirm once. The scene category is single-select
 * (an element binds at most one scene). Selection state is local; the host
 * receives the final id set on 确认 and persists it in one edit.
 */
export default function RelatedAssetPicker({
  open,
  candidates,
  boundIds,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  candidates: PickerCandidate[];
  boundIds: string[];
  onCancel: () => void;
  onConfirm: (selectedIds: string[]) => void;
}) {
  const { t } = useTranslation();
  const [filter, setFilter] = useState<"all" | PickerKind>("all");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  useEffect(() => {
    if (!open) return;
    setSelected(new Set(boundIds));
    setFilter("all");
    // boundIds is sampled once per opening; live churn mid-pick is ignored.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const kindLabel = (kind: PickerKind) =>
    kind === "material"
      ? t("r2v.fieldLabels.sources")
      : t(`blueprint.entityKinds.${kind}`);
  const presentKinds = useMemo(
    () =>
      (["character", "scene", "prop", "material"] as const).filter((kind) =>
        candidates.some((candidate) => candidate.kind === kind),
      ),
    [candidates],
  );
  const visible = candidates.filter(
    (candidate) => filter === "all" || candidate.kind === filter,
  );
  const toggle = (candidate: PickerCandidate) =>
    setSelected((previous) => {
      const next = new Set(previous);
      if (next.has(candidate.id)) {
        next.delete(candidate.id);
        return next;
      }
      if (candidate.kind === "scene") {
        for (const other of candidates) {
          if (other.kind === "scene") next.delete(other.id);
        }
      }
      next.add(candidate.id);
      return next;
    });

  return (
    <Modal
      open={open}
      onCancel={onCancel}
      width="min(720px, 94vw)"
      title={
        <span className="text-sm font-bold">{t("r2v.assetPickerTitle")}</span>
      }
      footer={
        <div className="flex justify-end gap-2">
          <Button size="small" onClick={onCancel}>
            {t("r2v.fullscreenCancel")}
          </Button>
          <Button
            size="small"
            type="primary"
            data-picker-confirm
            onClick={() => onConfirm(Array.from(selected))}
          >
            {t("r2v.assetPickerConfirm", { count: selected.size })}
          </Button>
        </div>
      }
      destroyOnHidden
    >
      {candidates.length === 0 ? (
        <div className="flex h-32 items-center justify-center rounded-lg border border-dashed border-[var(--color-border)] text-xs text-[var(--color-text-tertiary)]">
          {t("r2v.assetPickerEmpty")}
        </div>
      ) : (
        <div className="space-y-4">
          {presentKinds.length > 1 && (
            <div className="flex flex-wrap gap-1.5 pt-1">
              {(["all", ...presentKinds] as const).map((kind) => {
                const active = filter === kind;
                return (
                  <button
                    key={kind}
                    type="button"
                    data-picker-filter={kind}
                    onClick={() => setFilter(kind)}
                    className={`h-7 rounded-full px-3 text-xs font-medium transition-colors ${
                      active
                        ? "bg-[var(--color-text-primary)] text-[var(--color-bg-primary)]"
                        : "border border-[var(--color-border)] text-[var(--color-text-secondary)] hover:border-[var(--color-border-strong)] hover:text-[var(--color-text-primary)]"
                    }`}
                  >
                    {kind === "all" ? t("r2v.assetPickerAll") : kindLabel(kind)}
                  </button>
                );
              })}
            </div>
          )}
          <div className="grid max-h-[52vh] grid-cols-3 gap-2.5 overflow-y-auto pr-1 sm:grid-cols-4">
            {visible.map((candidate) => {
              const picked = selected.has(candidate.id);
              return (
                <button
                  key={candidate.id}
                  type="button"
                  data-picker-asset={candidate.id}
                  onClick={() => toggle(candidate)}
                  className="group text-left"
                >
                  <span
                    className={`relative block aspect-video w-full overflow-hidden rounded-lg border transition-colors ${
                      picked
                        ? "border-[var(--color-accent)] ring-1 ring-[var(--color-accent)]"
                        : candidate.thumbUrl
                        ? "border-[var(--color-border)] group-hover:border-[var(--color-border-strong)]"
                        : "border-dashed border-[var(--color-border-strong)] group-hover:border-[var(--color-border-strong)]"
                    } bg-[var(--color-bg-secondary)]`}
                  >
                    {candidate.thumbUrl ? (
                      <img
                        src={candidate.thumbUrl}
                        alt=""
                        loading="lazy"
                        className="h-full w-full object-cover"
                      />
                    ) : (
                      <span className="flex h-full w-full flex-col items-center justify-center gap-1">
                        <ImageIcon className="h-5 w-5 text-[var(--color-text-tertiary)]" />
                        <span className="text-[10px] text-[var(--color-text-tertiary)]">
                          {t("blueprint.notGenerated")}
                        </span>
                      </span>
                    )}
                    <span className="absolute right-1 top-1 rounded bg-black/55 px-1.5 py-0.5 text-[10px] font-medium text-white">
                      {kindLabel(candidate.kind)}
                    </span>
                    {picked && (
                      <span className="absolute left-1 top-1 flex h-4 w-4 items-center justify-center rounded-full bg-[var(--color-accent)] text-white">
                        <Check className="h-3 w-3" />
                      </span>
                    )}
                  </span>
                  <span className="mt-1 block truncate text-xs text-[var(--color-text-primary)]">
                    {candidate.name}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </Modal>
  );
}
