import { useTranslation } from "react-i18next";
import type { ProjectDocument } from "@/contracts/creator";
import { creatorTargetLabel } from "@/lib/creatorPresentation";
import { refImageThumbUrl } from "@/components/workbench/referenceThumbs";

/** Exact reviewed versions, projected as media and public names, never IDs. */
export default function ReviewReferenceImages({
  value,
  project,
}: {
  value: unknown;
  project?: ProjectDocument | null;
}) {
  const { t } = useTranslation();
  if (!Array.isArray(value) || !value.every((item) => typeof item === "string"))
    return (
      <p className="text-xs text-[var(--color-text-tertiary)]">
        {t("fileReview.previewUnavailable")}
      </p>
    );
  if (value.length === 0)
    return (
      <p className="text-xs text-[var(--color-text-tertiary)]">
        {t("fileReview.public.noReferenceImages")}
      </p>
    );
  return (
    <div className="grid grid-cols-2 gap-2">
      {value.map((id, index) => {
        const source = project?.assets.source_versions_by_id[id];
        const label = creatorTargetLabel(
          `${source ? "asset-version" : "artifact-version"}:${id}`,
          project,
        );
        const thumbnail = project ? refImageThumbUrl(project, null, id) : null;
        return (
          <figure
            key={`${id}-${index}`}
            className="min-w-0 overflow-hidden rounded border border-[var(--color-border)] bg-[var(--color-bg-secondary)]"
          >
            {thumbnail ? (
              <img
                src={thumbnail}
                alt={label}
                className="h-24 w-full object-contain"
              />
            ) : (
              <div className="flex h-24 items-center justify-center text-xs text-[var(--color-text-tertiary)]">
                {t("fileReview.previewUnavailable")}
              </div>
            )}
            <figcaption className="break-words px-2 py-1 text-[11px] text-[var(--color-text-secondary)]">
              {label}
            </figcaption>
          </figure>
        );
      })}
    </div>
  );
}
