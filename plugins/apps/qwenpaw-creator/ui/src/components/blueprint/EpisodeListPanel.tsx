import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import type { ProjectDocument } from "@/contracts/creator";
import {
  getArtifactVersionFrameUrl,
  getArtifactVersionMediaUrl,
  getAssetVersionFrameUrl,
  getAssetVersionMediaUrl,
} from "@/api/creator";
import { usePathname, useRouter } from "@/routing/navigation";
import { useProjectSnapshotStore } from "@/store/projectSnapshotStore";
import {
  roughCutFrameForElement,
  selectTimelineSummaries,
  type TimelineSummary,
} from "@/selectors/blueprintSelectors";
import { orderedTimelineElements } from "@/selectors/timelineElementSelectors";
import { TONE_DOT, type BlueprintTone } from "./tones";

function summaryTone(summary: TimelineSummary): BlueprintTone {
  if (summary.renderReady) return "done";
  if (summary.videoReady > 0) return "run";
  if (summary.hasScript) return "wait";
  return "idle";
}

function firstFrameUrl(
  project: ProjectDocument,
  summary: TimelineSummary,
): string | null {
  // Audio elements (e.g. a narration bed at tick 0) carry no picture; use
  // the first element that actually resolves to a rough-cut frame.
  for (const element of orderedTimelineElements(summary.timeline)) {
    if (!element.enabled) continue;
    const frame = roughCutFrameForElement(project, element);
    if (!frame.versionId) continue;
    const fromSource = frame.versionKind === "source";
    // Video artifacts can't render inside <img>; use the poster-frame endpoint.
    if (frame.mediaKind === "video") {
      return fromSource
        ? getAssetVersionFrameUrl(frame.versionId, 0, 160)
        : getArtifactVersionFrameUrl(frame.versionId, 0, 160);
    }
    return fromSource
      ? getAssetVersionMediaUrl(frame.versionId)
      : getArtifactVersionMediaUrl(frame.versionId);
  }
  return null;
}

function activeTimelineIdFromPath(pathname: string): string | null {
  const match = pathname.match(/\/t\/([^/]+)\//);
  return match ? decodeURIComponent(match[1]) : null;
}

/**
 * "剧集列表" tab of the workspace sidebar: one row per timeline with a
 * poster thumb, title and state; the row of the timeline being edited is
 * highlighted. Clicking a row opens that timeline's plan page.
 */
export default function EpisodeListPanel() {
  const { t } = useTranslation();
  const router = useRouter();
  const pathname = usePathname();
  const project = useProjectSnapshotStore((state) => state.project);
  const summaries = useMemo(
    () => (project ? selectTimelineSummaries(project) : []),
    [project],
  );
  if (!project) return null;
  const activeTimelineId = activeTimelineIdFromPath(pathname);

  return (
    <div
      data-episode-list-panel
      className="min-h-0 flex-1 space-y-1.5 overflow-y-auto px-3 py-2"
    >
      {summaries.length === 0 && (
        <p className="py-6 text-center text-[11px] text-[var(--color-text-tertiary)]">
          {t("blueprint.episodesCount", { count: 0 })}
        </p>
      )}
      {summaries.map((summary) => {
        const active = summary.timelineId === activeTimelineId;
        const tone = summaryTone(summary);
        const title =
          summary.title || t("blueprint.episodeN", { n: summary.index + 1 });
        const frameUrl = firstFrameUrl(project, summary);
        return (
          <button
            key={summary.timelineId}
            type="button"
            title={summary.synopsis || title}
            onClick={() =>
              router.push(
                `/project/${project.project_id}/t/${encodeURIComponent(
                  summary.timelineId,
                )}/plan`,
              )
            }
            className={`flex h-[54px] w-full items-center gap-2.5 rounded-lg border px-1.5 text-left transition-colors ${
              active
                ? "border-[var(--color-accent)]/40 bg-[var(--color-accent-soft)]"
                : "border-transparent hover:bg-[var(--color-bg-secondary)]"
            }`}
          >
            <span className="h-[42px] w-[71px] shrink-0 overflow-hidden rounded border border-[var(--color-border)] bg-[var(--color-bg-secondary)]">
              {frameUrl && (
                <img
                  src={frameUrl}
                  alt=""
                  loading="lazy"
                  className="h-full w-full object-cover"
                />
              )}
            </span>
            <span className="min-w-0 flex-1 leading-tight">
              <span className="block truncate text-xs font-medium text-[var(--color-text-primary)]">
                {title}
              </span>
              <span className="mt-0.5 flex items-center gap-1.5">
                <span
                  className={`h-1.5 w-1.5 shrink-0 rounded-full ${TONE_DOT[tone]}`}
                />
                <span className="truncate text-xs text-[var(--color-text-tertiary)]">
                  {t(`blueprint.episodeState.${tone}`)}
                </span>
              </span>
            </span>
          </button>
        );
      })}
    </div>
  );
}
