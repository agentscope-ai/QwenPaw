import { Fragment } from "react";
import {
  navigate,
  useParams,
  usePathname,
  useSearchParams,
} from "@/routing/navigation";
import { useProjectSnapshotStore } from "@/store/projectSnapshotStore";
import { selectPrimaryTimeline } from "@/selectors/timelineElementSelectors";
import { useTranslation } from "react-i18next";

interface Crumb {
  label: string;
  path?: string;
}

export function useBreadcrumbs(): Crumb[] {
  const { t } = useTranslation();
  const { id: projectId } = useParams();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const project = useProjectSnapshotStore((state) => state.project);
  const timeline = selectPrimaryTimeline(project);

  if (!projectId) return [];
  const base = `/project/${projectId}`;
  const parts = pathname.split("/").filter(Boolean);
  const routeSection = parts[2] || "";
  if (routeSection === "plan") {
    const crumbs: Crumb[] = [
      { label: t("nav.videoPlan"), path: `${base}/plan` },
    ];
    if (parts[3] === "element" && parts[4]) {
      // R2V workbench: /project/:id/plan/element/:elementId
      const elementId = decodeURIComponent(parts[4]);
      const element = timeline?.elements_by_id[elementId];
      crumbs.push({
        label: element?.label || elementId,
        path: `${base}/plan?element=${encodeURIComponent(elementId)}`,
      });
      crumbs.push({ label: t("nav.productionWorkbench") });
      return crumbs;
    }
    const elementId = searchParams.get("element");
    if (elementId) {
      const element = timeline?.elements_by_id[elementId];
      crumbs.push({ label: element?.label || elementId });
    }
    return crumbs;
  }

  if (routeSection === "assets") {
    const crumbs: Crumb[] = [
      { label: t("nav.assets"), path: `${base}/assets` },
    ];
    const selectedId = searchParams.get("select") || searchParams.get("asset");
    if (selectedId) {
      const selected =
        project?.assets.source_versions_by_id[selectedId] ??
        project?.assets.artifact_versions_by_id[selectedId];
      if (selected) crumbs.push({ label: selected.name });
    }
    return crumbs;
  }

  return [];
}

export default function Breadcrumb() {
  const { t } = useTranslation();
  const crumbs = useBreadcrumbs();
  if (crumbs.length === 0) return null;

  return (
    <nav
      className="flex min-w-0 items-center gap-1.5 text-xs text-[var(--color-text-secondary)]"
      aria-label={t("nav.breadcrumb")}
    >
      {crumbs.map((crumb, index) => {
        const isLast = index === crumbs.length - 1;
        return (
          <Fragment key={`${crumb.label}-${index}`}>
            {index > 0 && (
              <span className="text-[var(--color-text-tertiary)]">/</span>
            )}
            {crumb.path && !isLast ? (
              <button
                type="button"
                onClick={() => navigate(crumb.path!)}
                className="max-w-[160px] truncate rounded px-1 py-0.5 transition-colors hover:bg-[var(--color-bg-secondary)] hover:text-[var(--color-text-primary)]"
              >
                {crumb.label}
              </button>
            ) : (
              <span
                className={`max-w-[160px] truncate px-1 ${
                  isLast ? "font-medium text-[var(--color-text-primary)]" : ""
                }`}
              >
                {crumb.label}
              </span>
            )}
          </Fragment>
        );
      })}
    </nav>
  );
}
