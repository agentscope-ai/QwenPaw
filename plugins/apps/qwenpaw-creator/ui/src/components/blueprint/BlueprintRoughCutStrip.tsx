import { useCallback, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import {
  ChevronDown,
  ChevronUp,
  Clapperboard,
  Download,
  Film,
  Play,
  RotateCcw,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import type { ProjectDocument } from "@/contracts/creator";
import {
  getArtifactVersionMediaUrl,
  getAssetVersionMediaUrl,
  getTimelineRoughCutUrl,
} from "@/api/creator";
import {
  selectFinalFilmVersionId,
  selectRoughCutFrames,
  type RoughCutSource,
} from "@/selectors/blueprintSelectors";
import { selectLiveTimelineIds } from "@/selectors/timelineElementSelectors";

const SOURCE_STYLE: Record<RoughCutSource, string> = {
  final: "bg-[var(--color-success)]/90",
  storyboard: "bg-[var(--color-primary,#3b82f6)]/90",
  design: "bg-[var(--color-warning)]/90",
  none: "bg-black/50",
};

/** Sentinel playing id of the whole-film chip (never a real timeline id). */
const FULL_FILM_ID = "__full_film__";

/* ------------------------------------------------------------------ */
/* Cinema preview: a near-fullscreen floating overlay. The whole-film  */
/* chip plays the composed mp4; timeline chips play the story in       */
/* narrative order.                                                    */
/* ------------------------------------------------------------------ */

function PreviewCinema({
  project,
  startId,
  filmUrl,
  labelOf,
  srcOf,
  onClose,
}: {
  project: ProjectDocument;
  startId: string;
  /** Whole-film mp4 url; used when startId is the FULL_FILM_ID sentinel. */
  filmUrl: string | null;
  labelOf: (timelineId: string) => string;
  srcOf: (timelineId: string) => string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const wholeFilm = startId === FULL_FILM_ID;
  const initialId = startId;
  const [currentId, setCurrentId] = useState(initialId);
  const [segmentIndex, setSegmentIndex] = useState(1);
  const [ended, setEnded] = useState(false);
  const [error, setError] = useState(false);
  const [replayNonce, setReplayNonce] = useState(0);
  /** Intrinsic aspect ratio of the playing video; lets the frame hug it. */
  const [aspectRatio, setAspectRatio] = useState<number | null>(null);

  useEffect(() => {
    setCurrentId(initialId);
    setSegmentIndex(1);
    setEnded(false);
    setError(false);
    setAspectRatio(null);
  }, [startId, initialId]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const liveOrder = useMemo(() => selectLiveTimelineIds(project), [project]);

  const advanceTo = useCallback((timelineId: string) => {
    setCurrentId(timelineId);
    setSegmentIndex((index) => index + 1);
    setEnded(false);
    setError(false);
    setAspectRatio(null);
  }, []);

  const handleEnded = useCallback(() => {
    if (wholeFilm) {
      setEnded(true);
      return;
    }
    // Linear story: fall through the live timelines in narrative order.
    const next = liveOrder[liveOrder.indexOf(currentId) + 1];
    if (next) {
      advanceTo(next);
      return;
    }
    setEnded(true);
  }, [wholeFilm, currentId, liveOrder, advanceTo]);

  const replay = useCallback(() => {
    setReplayNonce((nonce) => nonce + 1);
    if (wholeFilm) {
      setEnded(false);
      setError(false);
      return;
    }
    setSegmentIndex(0);
    advanceTo(liveOrder[0] ?? startId);
  }, [wholeFilm, liveOrder, startId, advanceTo]);

  const badgeLabel = wholeFilm
    ? `${project.name} · ${t("blueprint.finalCutBadge")}`
    : `${segmentIndex} · ${labelOf(currentId)}`;

  // Portal to <body>: the strip's backdrop-filter would otherwise become
  // the containing block for this fixed overlay and clip it.
  return createPortal(
    <div
      data-roughcut-cinema
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-md"
      onClick={onClose}
    >
      <div
        data-roughcut-player
        className="relative w-fit max-w-[92vw] overflow-hidden rounded-3xl border border-white/10 bg-black shadow-[0_32px_96px_rgba(0,0,0,.6)]"
        onClick={(event) => event.stopPropagation()}
      >
        {error ? (
          <div className="flex h-40 w-80 items-center justify-center px-6 text-center text-xs text-white/70">
            {t("blueprint.roughCutFailed")}
          </div>
        ) : (
          // The frame hugs the video's own aspect ratio (measured from
          // metadata): width = min(92vw, 82vh × ratio) — no letterbox bars
          // in either orientation.
          <video
            key={`${currentId}:${replayNonce}`}
            src={wholeFilm ? filmUrl ?? undefined : srcOf(currentId)}
            controls
            autoPlay
            playsInline
            onLoadedMetadata={(event) => {
              const { videoWidth, videoHeight } = event.currentTarget;
              if (videoWidth > 0 && videoHeight > 0) {
                setAspectRatio(videoWidth / videoHeight);
              }
            }}
            onEnded={handleEnded}
            onError={() => setError(true)}
            style={
              aspectRatio
                ? {
                    width: `min(92vw, calc(82vh * ${aspectRatio}))`,
                    aspectRatio: String(aspectRatio),
                  }
                : undefined
            }
            className={`block bg-black ${
              aspectRatio
                ? "h-auto max-h-[82vh] max-w-[92vw]"
                : "h-[min(82vh,900px)] w-auto max-w-full object-contain"
            }`}
          />
        )}

        {/* Playback finished — offer replay from the entry. */}
        {ended && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-black/70 backdrop-blur-sm">
            <button
              type="button"
              onClick={replay}
              className="inline-flex h-16 w-16 items-center justify-center rounded-full border-2 border-[var(--color-accent)] bg-[var(--color-accent)]/25 text-white transition-all hover:scale-105 hover:bg-[var(--color-accent)]/60"
              title={t("blueprint.previewReplay")}
            >
              <RotateCcw className="h-6 w-6" />
            </button>
            <p className="text-xs font-semibold text-white/80">
              {t("blueprint.previewReplay")}
            </p>
          </div>
        )}

        <span className="absolute left-3 top-3 rounded-full bg-black/45 px-2.5 py-1 text-[10px] font-semibold text-white backdrop-blur-md">
          {badgeLabel}
        </span>
        <button
          type="button"
          onClick={onClose}
          title={t("blueprint.closeRoughCutPlayer")}
          className="absolute right-3 top-3 inline-flex h-8 w-8 items-center justify-center rounded-full bg-black/45 text-white backdrop-blur-md transition-all hover:scale-105 hover:bg-black/75"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>,
    document.body,
  );
}

interface BlueprintRoughCutStripProps {
  project: ProjectDocument;
  onSelectTimeline: (timelineId: string) => void;
}

/**
 * Rough-cut preview strip (plan §4.8): one frame per enabled element, sourced
 * purely from existing artifacts — selected element_video ▸ storyboard image ▸
 * referenced entity design ▸ placeholder. Clicking a frame opens the owning
 * timeline's script panel; play chips open the floating cinema overlay.
 */
export default function BlueprintRoughCutStrip({
  project,
  onSelectTimeline,
}: BlueprintRoughCutStripProps) {
  const { t } = useTranslation();
  const [collapsed, setCollapsed] = useState(false);
  const [playingId, setPlayingId] = useState<string | null>(null);
  const frames = useMemo(() => selectRoughCutFrames(project), [project]);
  const readyCount = frames.filter((frame) => frame.source === "final").length;
  const timelineIds = useMemo(
    () => [...new Set(frames.map((frame) => frame.timelineId))],
    [frames],
  );
  const filmVersionId = useMemo(
    () => selectFinalFilmVersionId(project),
    [project],
  );
  const filmUrl = filmVersionId
    ? getArtifactVersionMediaUrl(filmVersionId)
    : null;
  if (!frames.length && !filmUrl) return null;

  const timelineLabelOf = (timelineId: string) => {
    const timeline = project.timelines.items[timelineId];
    const index = frames.find((frame) => frame.timelineId === timelineId)
      ?.timelineIndex;
    return timeline?.title || t("blueprint.episodeN", { n: (index ?? 0) + 1 });
  };

  const finalCutUrlOf = (timelineId: string) => {
    const slot =
      project.assets.artifact_slots_by_id[`timeline:${timelineId}:render`];
    if (slot?.kind !== "final_video" || !slot.selected_version_id) return null;
    return getArtifactVersionMediaUrl(slot.selected_version_id);
  };

  const togglePlay = (timelineId: string) => {
    setPlayingId((current) => (current === timelineId ? null : timelineId));
  };

  return (
    <section
      data-blueprint-roughcut
      className="relative shrink-0 border-t border-[var(--color-border)] bg-[var(--color-bg-primary)]/70 px-5 py-2 backdrop-blur"
    >
      <div className="flex items-center gap-2.5">
        <span className="inline-flex shrink-0 items-center gap-1.5 text-xs font-semibold text-[var(--color-text-primary)]">
          <Clapperboard className="h-3.5 w-3.5 text-[var(--color-accent)]" />
          {t("blueprint.roughCut")}
        </span>
        <button
          type="button"
          data-roughcut-preview-all
          onClick={() =>
            setPlayingId(selectLiveTimelineIds(project)[0] ?? null)
          }
          className="inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full bg-[var(--color-text-primary)] px-2.5 py-1 text-[10px] font-bold text-[var(--color-bg-primary)] shadow-[0_2px_8px_rgba(0,0,0,.2)] transition-all hover:-translate-y-px hover:opacity-90"
        >
          <Play className="h-3 w-3" />
          {t("blueprint.previewAll")}
        </button>
        <span className="hidden min-w-0 truncate text-[11px] text-[var(--color-text-tertiary)] lg:block">
          {t("blueprint.roughCutHint", {
            ready: readyCount,
            total: frames.length,
          })}
        </span>
        <span className="ml-auto flex min-w-0 shrink items-center gap-1.5 overflow-x-auto py-0.5 [scrollbar-width:none]">
          {Boolean(filmUrl) && (
            <button
              type="button"
              data-roughcut-play-film
              onClick={() => togglePlay(FULL_FILM_ID)}
              title={t("blueprint.playFullFilm")}
              className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-semibold transition-colors ${
                playingId === FULL_FILM_ID
                  ? "border-[var(--color-accent)] bg-[var(--color-accent)]/15 text-[var(--color-accent)]"
                  : "border-[var(--color-border)] text-[var(--color-text-secondary)] hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]"
              }`}
            >
              <Film className="h-3 w-3" />
              {t("blueprint.playFullFilm")}
              <span className="rounded bg-[var(--color-success)]/15 px-1 text-[9px] font-bold text-[var(--color-success)]">
                {t("blueprint.finalCutBadge")}
              </span>
            </button>
          )}
          <button
            type="button"
            onClick={() => setCollapsed((value) => !value)}
            className="icon-button !h-7 !w-7 shrink-0"
            title={
              collapsed
                ? t("blueprint.expandRoughCut")
                : t("blueprint.collapseRoughCut")
            }
          >
            {collapsed ? (
              <ChevronUp className="h-3.5 w-3.5" />
            ) : (
              <ChevronDown className="h-3.5 w-3.5" />
            )}
          </button>
        </span>
      </div>
      {playingId && (
        <PreviewCinema
          project={project}
          startId={playingId}
          filmUrl={filmUrl}
          labelOf={timelineLabelOf}
          srcOf={(timelineId) =>
            finalCutUrlOf(timelineId) ??
            getTimelineRoughCutUrl(project.project_id, timelineId)
          }
          onClose={() => setPlayingId(null)}
        />
      )}
      {!collapsed && (
        <div className="mt-2 flex items-stretch gap-3 overflow-x-auto pb-1.5">
          {timelineIds.map((timelineId) => {
            const groupFrames = frames.filter(
              (frame) => frame.timelineId === timelineId,
            );
            if (!groupFrames.length) return null;
            const timeline = project.timelines.items[timelineId];
            const groupLabel = timelineLabelOf(timelineId);
            const finalUrl = finalCutUrlOf(timelineId);
            const ticksPerSecond = timeline?.ticks_per_second || 1000;
            return (
              <div
                key={timelineId}
                data-roughcut-group={timelineId}
                className="flex shrink-0 flex-col gap-1.5 rounded-md border border-[var(--color-border)] bg-[var(--color-bg-secondary)]/60 p-2"
              >
                <div className="flex items-center gap-1.5">
                  <button
                    type="button"
                    data-roughcut-play={timelineId}
                    onClick={() => togglePlay(timelineId)}
                    title={t("blueprint.playRoughCut")}
                    className={`inline-flex h-5 w-5 shrink-0 items-center justify-center rounded transition-colors ${
                      playingId === timelineId
                        ? "text-[var(--color-accent)]"
                        : "text-[var(--color-text-secondary)] hover:text-[var(--color-accent)]"
                    }`}
                  >
                    <Play className="h-3.5 w-3.5" />
                  </button>
                  <span className="max-w-[240px] truncate text-xs font-medium text-[var(--color-text-primary)]">
                    {groupLabel}
                  </span>
                  {finalUrl && (
                    <span className="shrink-0 rounded bg-[var(--color-success)]/15 px-1 text-[9px] font-bold text-[var(--color-success)]">
                      {t("blueprint.finalCutBadge")}
                    </span>
                  )}
                  {finalUrl && (
                    <a
                      href={finalUrl}
                      download={`${timelineId.replace(/:/g, "_")}-final.mp4`}
                      data-roughcut-download={timelineId}
                      title={t("blueprint.downloadFinalCut")}
                      className="ml-auto inline-flex h-5 w-5 shrink-0 items-center justify-center rounded text-[var(--color-text-tertiary)] transition-colors hover:text-[var(--color-accent)]"
                    >
                      <Download className="h-3.5 w-3.5" />
                    </a>
                  )}
                </div>
                <div className="flex items-start gap-1.5">
                  {groupFrames.map((frame) => {
                    const url = frame.versionId
                      ? frame.versionKind === "source"
                        ? getAssetVersionMediaUrl(frame.versionId)
                        : getArtifactVersionMediaUrl(frame.versionId)
                      : null;
                    const element = timeline?.elements_by_id[frame.elementId];
                    const seconds = element
                      ? Math.max(
                          0,
                          Math.round(
                            element.span.duration_tick / ticksPerSecond,
                          ),
                        )
                      : null;
                    const durationLabel =
                      seconds != null
                        ? `${String(Math.floor(seconds / 60)).padStart(
                            2,
                            "0",
                          )}:${String(seconds % 60).padStart(2, "0")}`
                        : null;
                    return (
                      <button
                        key={frame.key}
                        type="button"
                        data-roughcut-frame={frame.key}
                        title={`${frame.label} · ${t(
                          `blueprint.frameSource.${frame.source}`,
                        )}`}
                        onClick={() => onSelectTimeline(frame.timelineId)}
                        className="group w-[139px] shrink-0 text-left"
                      >
                        <span className="relative block h-[82px] w-full overflow-hidden rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)] transition-colors group-hover:border-[var(--color-accent)]">
                          {url &&
                            (frame.mediaKind === "video" ? (
                              <video
                                src={url}
                                muted
                                preload="metadata"
                                className="h-full w-full object-cover"
                              />
                            ) : (
                              <img
                                src={url}
                                alt=""
                                loading="lazy"
                                className="h-full w-full object-cover"
                              />
                            ))}
                          <span
                            className={`absolute left-0 top-0 rounded-br px-1 py-px text-[8px] font-bold text-white ${
                              SOURCE_STYLE[frame.source]
                            }`}
                          >
                            {t(`blueprint.frameSource.${frame.source}`)}
                          </span>
                          {durationLabel && (
                            <span className="absolute bottom-1 right-1 rounded bg-black/65 px-1 text-[10px] font-semibold leading-4 text-white">
                              {durationLabel}
                            </span>
                          )}
                        </span>
                        <span className="mt-1 block truncate text-xs leading-4 text-[var(--color-text-primary)]/90">
                          {frame.label}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
