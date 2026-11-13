import { useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  ClipboardList,
  Lock,
  PencilRuler,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import type { EditPlanDocument } from "@/contracts/creator";

interface EditPlanCardProps {
  editPlan: EditPlanDocument | null | undefined;
}

function DialBadge({ label, value }: { label: string; value: string }) {
  const tone =
    value === "high"
      ? "bg-[var(--color-accent-soft)] text-[var(--color-accent)]"
      : value === "low"
      ? "bg-[var(--color-bg-secondary)] text-[var(--color-text-tertiary)]"
      : "bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)]";
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] ${tone}`}
    >
      {label}
      <b className="font-semibold uppercase">{value}</b>
    </span>
  );
}

/**
 * Read-only presentation of one Timeline's taste contract (edit_plan).
 * The plan is written by the AI editing director before assembly; edits go
 * through the conversation ("add to chat"), never through this card.
 */
export default function EditPlanCard({ editPlan }: EditPlanCardProps) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  if (!editPlan) return null;
  const hasContent =
    editPlan.concept.trim() ||
    editPlan.pacing.trim() ||
    editPlan.signature_device.trim();
  if (!hasContent) return null;
  const ledger = editPlan.scene_ledger ?? [];
  const lockedCount = ledger.filter((row) => row.status === "locked").length;
  const slots: Array<[string, string]> = [
    [t("editPlan.opening"), editPlan.design_floor.opening],
    [t("editPlan.transitions"), editPlan.design_floor.transitions],
    [t("editPlan.body"), editPlan.design_floor.body],
    [t("editPlan.ending"), editPlan.design_floor.ending],
  ];
  return (
    <div
      data-edit-plan-card
      className="mb-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)] px-3 py-2"
    >
      <button
        type="button"
        className="flex w-full items-center gap-2 text-left"
        onClick={() => setExpanded((value) => !value)}
      >
        <ClipboardList className="h-3.5 w-3.5 shrink-0 text-[var(--color-accent)]" />
        <span className="min-w-0 flex-1 truncate text-xs font-semibold text-[var(--color-text-primary)]">
          {editPlan.concept.trim() || t("editPlan.title")}
        </span>
        {ledger.length > 0 && (
          <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-[var(--color-bg-primary)] px-2 py-0.5 text-[10px] text-[var(--color-text-secondary)]">
            <Lock className="h-3 w-3" />
            {t("editPlan.lockedScenes", {
              locked: lockedCount,
              total: ledger.length,
            })}
          </span>
        )}
        {expanded ? (
          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-[var(--color-text-tertiary)]" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 shrink-0 text-[var(--color-text-tertiary)]" />
        )}
      </button>
      {expanded && (
        <div className="mt-2 space-y-2 border-t border-[var(--color-border)] pt-2">
          <div className="flex flex-wrap items-center gap-1.5">
            <DialBadge
              label={t("editPlan.energy")}
              value={editPlan.dials.energy}
            />
            <DialBadge
              label={t("editPlan.density")}
              value={editPlan.dials.density}
            />
            <DialBadge
              label={t("editPlan.decoration")}
              value={editPlan.dials.decoration}
            />
          </div>
          {editPlan.signature_device.trim() && (
            <p className="flex items-start gap-1.5 text-[11px] leading-4 text-[var(--color-text-secondary)]">
              <PencilRuler className="mt-0.5 h-3 w-3 shrink-0" />
              <span>
                <b>{t("editPlan.signatureDevice")}</b>
                {editPlan.signature_device}
              </span>
            </p>
          )}
          {editPlan.pacing.trim() && (
            <p className="text-[11px] leading-4 text-[var(--color-text-secondary)]">
              <b>{t("editPlan.pacing")}</b>
              {editPlan.pacing}
            </p>
          )}
          <dl className="space-y-1">
            {slots
              .filter(([, value]) => value.trim())
              .map(([label, value]) => (
                <div key={label} className="flex gap-1.5 text-[11px] leading-4">
                  <dt className="shrink-0 font-semibold text-[var(--color-text-secondary)]">
                    {label}
                  </dt>
                  <dd className="min-w-0 text-[var(--color-text-tertiary)]">
                    {value}
                  </dd>
                </div>
              ))}
          </dl>
          {ledger.length > 0 && (
            <ul className="space-y-1">
              {ledger.map((row) => (
                <li
                  key={row.scene_id}
                  className="flex items-center gap-1.5 text-[11px] text-[var(--color-text-secondary)]"
                >
                  <span
                    className={`inline-flex shrink-0 items-center rounded-full px-1.5 py-0.5 text-[9px] font-semibold uppercase ${
                      row.status === "locked"
                        ? "bg-[var(--color-success-soft,rgba(34,197,94,0.12))] text-[var(--color-success,#16a34a)]"
                        : "bg-[var(--color-bg-primary)] text-[var(--color-text-tertiary)]"
                    }`}
                  >
                    {row.status === "locked"
                      ? t("editPlan.locked")
                      : t("editPlan.draft")}
                  </span>
                  <span className="min-w-0 truncate">
                    {row.label || row.scene_id}
                  </span>
                  {row.review_round > 0 && (
                    <span className="shrink-0 text-[9px] text-[var(--color-text-tertiary)]">
                      {t("editPlan.reviewRound", { round: row.review_round })}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
