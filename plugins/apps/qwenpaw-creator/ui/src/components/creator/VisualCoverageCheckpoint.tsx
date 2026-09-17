import { useTranslation } from "react-i18next";
import { CircleAlert, CircleCheck } from "lucide-react";
import type {
  VisualCoverageReport,
  VisualCoverageStatus,
} from "@/selectors/visualVariantCoverage";
import { visualVariantLabel } from "@/lib/visualVariants";

const STATUS_LABEL_KEYS: Record<VisualCoverageStatus, string> = {
  covered: "visualCoverage.covered",
  missing_required_variant: "visualCoverage.variantUndefined",
  unassigned_variant: "visualCoverage.elementUnbound",
  missing_artifact: "visualCoverage.noActiveProduct",
};

const KIND_LABEL_KEYS: Record<string, string> = {
  character: "visualCoverage.character",
  scene: "visualCoverage.scene",
  prop: "visualCoverage.prop",
};

export default function VisualCoverageCheckpoint({
  report,
}: {
  report: VisualCoverageReport;
}) {
  const { t } = useTranslation();
  if (!report.total) return null;
  return (
    <details
      data-visual-coverage-checkpoint
      className={`shrink-0 border-b px-5 py-2 ${
        report.issueCount
          ? "border-amber-200 bg-amber-50/80"
          : "border-emerald-200 bg-emerald-50/70"
      }`}
    >
      <summary className="flex cursor-pointer list-none items-center gap-2 text-xs font-semibold text-[var(--color-text-primary)]">
        {report.issueCount ? (
          <CircleAlert className="h-4 w-4 text-amber-600" />
        ) : (
          <CircleCheck className="h-4 w-4 text-emerald-600" />
        )}
        {t("visualCoverage.title", {
          covered: report.covered,
          total: report.total,
        })}
        <span className="font-normal text-[var(--color-text-secondary)]">
          {report.issueCount
            ? t("visualCoverage.issuesToCheck", { count: report.issueCount })
            : t("visualCoverage.allBound")}
        </span>
      </summary>
      <div className="mt-2 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
        {report.items.map((item) => (
          <div
            key={item.entity.entity_id}
            className="rounded-lg border border-black/5 bg-white/80 p-2.5 text-[11px]"
          >
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="truncate font-semibold text-[var(--color-text-primary)]">
                  {item.entity.name}
                </div>
                <div className="text-[var(--color-text-tertiary)]">
                  {t(KIND_LABEL_KEYS[item.entity.kind])} ·{" "}
                  {item.referencedElementIds.length}{" "}
                  {t("visualCoverage.elementRefs")}
                </div>
                {item.entity.required_variant_ids.length > 0 && (
                  <div className="text-[var(--color-text-tertiary)]">
                    {t("visualCoverage.requiredVariants")}{" "}
                    {item.definedRequiredCount}/
                    {item.entity.required_variant_ids.length}
                  </div>
                )}
              </div>
              <span
                className={`shrink-0 rounded-full px-2 py-0.5 ${
                  item.status === "covered"
                    ? "bg-emerald-100 text-emerald-700"
                    : "bg-amber-100 text-amber-700"
                }`}
              >
                {t(STATUS_LABEL_KEYS[item.status])}
              </span>
            </div>
            {item.unassignedElementIds.length > 0 && (
              <div className="mt-2 rounded bg-amber-50 px-2 py-1 text-amber-700">
                {item.unassignedElementIds.length}{" "}
                {t("visualCoverage.elementsUnspecified")}
              </div>
            )}
            {item.missingVariantIds.length > 0 && (
              <div className="mt-2 rounded bg-amber-50 px-2 py-1 text-amber-700">
                {t("visualCoverage.missing")}
                {item.missingVariantIds.join("、")}
              </div>
            )}
            {item.variants.length > 0 && (
              <div className="mt-2 space-y-1">
                {item.variants.map((variant) => (
                  <div
                    key={variant.variant.variant_id}
                    className="flex items-center justify-between gap-2 text-[var(--color-text-secondary)]"
                  >
                    <span className="min-w-0 truncate">
                      {visualVariantLabel(variant.variant)} ·{" "}
                      {variant.referencedElementIds.length}{" "}
                      {t("visualCoverage.elements")}
                    </span>
                    <span
                      className={
                        variant.selectedAvailable
                          ? "text-emerald-700"
                          : "text-amber-700"
                      }
                    >
                      {variant.selectedAvailable
                        ? `${t("visualCoverage.activeProducts")}${
                            variant.generatedCount
                          } ${t("visualCoverage.products")}`
                        : `${variant.generatedCount} ${t(
                            "visualCoverage.productsUnselected",
                          )}`}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </details>
  );
}
