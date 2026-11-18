import { useTranslation } from "react-i18next";
import { X } from "lucide-react";
import { chipLabel, type AttachmentDraft } from "./useProjectLaunch";

interface AttachmentChipProps {
  att: AttachmentDraft;
  onToggleScript: (id: string) => void;
  onRemove: (id: string) => void;
  /** Tailwind max-width utility so each composer keeps its own chip width. */
  maxWidthClass?: string;
}

/**
 * One attachment pill shared by both composers. A file detected as
 * script-like exposes a two-segment 剧本 / 素材 switch — creation lands at
 * most one script on the single default Timeline, so marking one clears the
 * rest. Every other attachment stays a plain removable chip.
 */
export default function AttachmentChip({
  att,
  onToggleScript,
  onRemove,
  maxWidthClass = "max-w-[260px]",
}: AttachmentChipProps) {
  const { t } = useTranslation();
  const { tag, name } = chipLabel(att);
  const scriptable = att.kind === "file" && att.scriptKind !== "none";
  const asScript = att.kind === "file" && att.asScript;

  const segment =
    "cursor-pointer rounded-full px-1.5 py-0.5 text-[10px] font-semibold transition-colors";
  const segmentOn = "bg-[var(--color-accent)] text-white";
  const segmentOff =
    "text-[var(--color-text-tertiary)] hover:text-[var(--color-text-secondary)]";

  return (
    <span
      className={`inline-flex ${maxWidthClass} items-center gap-1.5 rounded-full border border-[var(--color-border)] bg-[var(--color-bg-secondary)] py-1 pl-2 pr-1 text-[11px] text-[var(--color-text-secondary)]`}
    >
      <b className="shrink-0 text-[10px] text-[var(--color-accent)]">{tag}</b>
      <span className="min-w-0 truncate">{name}</span>
      {asScript && (
        <span className="shrink-0 rounded-full bg-[var(--color-accent-soft)] px-1.5 py-0.5 text-[10px] font-semibold text-[var(--color-accent)]">
          {t("home.scriptChipBadge")}
        </span>
      )}
      {scriptable && (
        <span
          title={t("home.scriptChipHint")}
          className="inline-flex shrink-0 items-center gap-0.5 rounded-full border border-[var(--color-border)] bg-[var(--color-bg-primary)] p-0.5"
        >
          <button
            type="button"
            aria-pressed={asScript}
            onClick={() => {
              if (!asScript) onToggleScript(att.id);
            }}
            className={`${segment} ${asScript ? segmentOn : segmentOff}`}
          >
            {t("home.scriptChipAsScript")}
          </button>
          <button
            type="button"
            aria-pressed={!asScript}
            onClick={() => {
              if (asScript) onToggleScript(att.id);
            }}
            className={`${segment} ${!asScript ? segmentOn : segmentOff}`}
          >
            {t("home.scriptChipAsMaterial")}
          </button>
        </span>
      )}
      <button
        type="button"
        onClick={() => onRemove(att.id)}
        className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full hover:bg-[var(--color-border)]"
        aria-label={t("home.removeAttachment")}
      >
        <X className="h-2.5 w-2.5" />
      </button>
    </span>
  );
}
