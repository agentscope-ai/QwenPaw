import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Clock3, ImageOff, Loader2 } from "lucide-react";
import type {
  ElementLocationDocument,
  MotionGraphicDocument,
  ProjectDocument,
  TaskView,
  TimelineDocument,
} from "@/contracts/creator";
import {
  fetchMotionDocument,
  getMotionDocumentPosterUrl,
} from "@/api/creator/media";
import type { ElementPlayback } from "@/selectors/elementPlaybackSelectors";
import {
  ELEMENT_PLAYBACK_STATUS_LABEL,
  playbackLayersInWindow,
  transitionOpacityAtTick,
} from "@/selectors/elementPlaybackSelectors";
import {
  overlayContentKind,
  resolveElementVisualMeta,
} from "@/selectors/timelineElementSelectors";
import {
  InterviewSummaryBox,
  PetOsBubble,
} from "@/components/timeline/OverlayCopyLayer";
import { useTranslation } from "react-i18next";
import i18n from "@/i18n";

interface TimelineLivePreviewProps {
  project: ProjectDocument;
  timeline: TimelineDocument;
  durationTick: number;
  playheadTick: number;
  playing: boolean;
  muted: boolean;
  tasks: TaskView[];
  onPlayheadChange: (tick: number) => void;
  onPlayingChange: (playing: boolean) => void;
}

/** Max allowed drift (seconds) between a video layer and the playhead before pulling it back. */
const DRIFT_TOLERANCE_SECONDS = 0.3;
/** Looser drift bound while playing: decode hiccups recover on their own and
 * every correction seek makes the element report `seeking`, so aggressive
 * pull-backs caused visible "locating frame" flashes mid-playback. */
const PLAYING_DRIFT_TOLERANCE_SECONDS = 0.75;
/** Minimum spacing between correction seeks on one element while playing. */
const PLAYING_SEEK_INTERVAL_MS = 1_000;
/** A transiently incomplete frame (seek/buffer on an already-complete
 * composite) keeps showing the last painted frame this long before the
 * opaque notice takes over. Cold starts still cover immediately. */
const INCOMPLETE_NOTICE_DELAY_MS = 300;
const RETIRED_MOTION_MOTIFS = new Set([
  "speed_lines",
  "side_eye",
  "sassy_cat",
  "surprised_cat",
  "happy_cat",
  "confused_cat",
]);

function aspectRatioStyle(aspectRatio: string): string {
  const match = /^(\d+(?:\.\d+)?)[:x](\d+(?:\.\d+)?)$/.exec(aspectRatio.trim());
  if (!match) return "16 / 9";
  return `${match[1]} / ${match[2]}`;
}

/** Normalized canvas coordinates → percentage positioning within the stage
 * (same convention as ElementDetail's location box). */
function locationBoxStyle(
  location: ElementLocationDocument | null,
): React.CSSProperties {
  if (!location) {
    return { left: 0, top: 0, width: "100%", height: "100%" };
  }
  return {
    left: `${(location.x - location.anchor_x * location.width) * 100}%`,
    top: `${(location.y - location.anchor_y * location.height) * 100}%`,
    width: `${location.width * 100}%`,
    height: `${location.height * 100}%`,
    transform: location.rotation_degrees
      ? `rotate(${location.rotation_degrees}deg)`
      : undefined,
    opacity: location.opacity,
  };
}

function isFullFrame(location: ElementLocationDocument | null): boolean {
  if (!location) return true;
  return location.width >= 0.9 && location.height >= 0.9;
}

function mediaTargetSeconds(
  layer: ElementPlayback,
  playheadTick: number,
  ticksPerSecond: number,
): number {
  const media = layer.media!;
  const localSeconds =
    Math.max(0, playheadTick - layer.element.span.start_tick) / ticksPerSecond;
  let offset = localSeconds * media.playbackRate;

  const sourceWindowSeconds =
    media.sourceOutSeconds != null
      ? media.sourceOutSeconds - media.sourceInSeconds
      : media.durationSeconds;
  const effectiveWindowSeconds = Math.min(
    sourceWindowSeconds ?? Infinity,
    media.durationSeconds ?? Infinity,
  );

  if (media.loop && effectiveWindowSeconds && effectiveWindowSeconds > 0) {
    offset %= effectiveWindowSeconds;
  } else if (effectiveWindowSeconds && offset > effectiveWindowSeconds) {
    offset = Math.max(0, effectiveWindowSeconds - 0.033);
  }

  return media.sourceInSeconds + offset;
}

/**
 * Clamp a metadata-derived seek target to what the mounted element can
 * actually reach. Metadata duration may exceed the real decoded duration
 * by a few frames; an unreachable target would otherwise keep the drift
 * check failing forever and pin the "正在定位画面" notice.
 */
function reachableTargetSeconds(
  target: number,
  node: HTMLVideoElement,
): number {
  if (!Number.isFinite(node.duration)) return target;
  return Math.min(target, Math.max(0, node.duration - 0.033));
}

function PlaceholderLayer({ layer }: { layer: ElementPlayback }) {
  const { t } = useTranslation();
  const { element, status } = layer;
  const meta = resolveElementVisualMeta(element);
  const label = i18n.t(ELEMENT_PLAYBACK_STATUS_LABEL[status]);
  const fullFrame = isFullFrame(element.location);
  const StatusIcon =
    status === "generating" ? Loader2 : status === "queued" ? Clock3 : ImageOff;
  if (fullFrame) {
    return (
      <div
        data-live-placeholder={element.element_id}
        data-live-placeholder-state={status}
        className="absolute flex flex-col items-center justify-center gap-2 bg-[radial-gradient(circle_at_center,#2b2521_0,#161210_62%,#0d0b0a_100%)] text-center"
        style={locationBoxStyle(element.location)}
      >
        <StatusIcon
          className={`h-7 w-7 ${
            status === "generating" ? "animate-spin" : ""
          } ${
            status === "failed" ? "text-[var(--color-danger)]" : "text-white/70"
          }`}
        />
        <span className="max-w-[70%] truncate text-sm font-semibold text-white/85">
          {element.label || meta.label}
        </span>
        <span
          className="rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
          style={{ color: meta.color, background: `${meta.color}26` }}
        >
          {meta.label} ·{" "}
          {status === "generating" ? t("livePreview.generating") : label}
        </span>
        {status === "generating" && (
          <div className="agent-working-shimmer mt-1 h-1 w-32 rounded-full bg-white/15" />
        )}
      </div>
    );
  }
  return (
    <div
      data-live-placeholder={element.element_id}
      data-live-placeholder-state={status}
      className="absolute flex items-center justify-center rounded-lg border border-dashed border-white/45 bg-black/30"
      style={locationBoxStyle(element.location)}
    >
      <span className="inline-flex max-w-full items-center gap-1 truncate rounded-full bg-black/55 px-2 py-0.5 text-[10px] font-semibold text-white/90">
        <StatusIcon
          className={`h-3 w-3 shrink-0 ${
            status === "generating" ? "animate-spin" : ""
          }`}
        />
        {element.label || meta.label} · {label}
      </span>
    </div>
  );
}

function TextOverlayLayer({
  layer,
  stageWidth,
  stageHeight,
}: {
  layer: ElementPlayback;
  stageWidth: number;
  stageHeight: number;
}) {
  const { element } = layer;
  if (element.creation.type !== "overlay") return null;
  // Deterministic copy rendering identical to the final compositor, so the
  // preview matches the final render.
  return (
    <div
      data-live-text-overlay={element.element_id}
      className="absolute"
      style={locationBoxStyle(element.location)}
    >
      {element.creation.vibe !== "summary" &&
      element.creation.overlay_kind !== "interview_summary" ? (
        <PetOsBubble
          text={element.creation.text}
          vibe={element.creation.vibe}
          stageWidth={stageWidth}
        />
      ) : (
        <InterviewSummaryBox
          text={element.creation.text}
          stageWidth={stageWidth}
          stageHeight={stageHeight}
        />
      )}
    </div>
  );
}

export function syncMotionAnimation(
  animation: Animation,
  localTimeMs: number,
  playing: boolean,
) {
  const endTime = animation.effect?.getComputedTiming().endTime ?? Infinity;
  const finiteEnd = Number.isFinite(endTime) ? Number(endTime) : null;
  animation.currentTime =
    finiteEnd === null ? localTimeMs : Math.min(localTimeMs, finiteEnd);

  // Calling play() on a finished finite entrance animation auto-rewinds it
  // to its transparent first frame. Keep it filled at the final keyframe;
  // only active/infinite animations should advance with the preview clock.
  if (!playing || (finiteEnd !== null && localTimeMs >= finiteEnd)) {
    animation.pause();
  } else {
    animation.play();
  }
}

export function motionExitProgress(
  exitStyle: string | undefined,
  localTimeMs: number,
  durationMs: number,
) {
  if (!exitStyle || exitStyle === "none" || durationMs <= 0) return 0;
  const progress = localTimeMs / durationMs;
  return Math.max(0, Math.min(1, (progress - 0.85) / 0.15));
}

function motionDataSetting(html: string, name: string): string | undefined {
  const match = new RegExp(`data-motion-${name}=["']([^"']+)["']`, "i").exec(
    html,
  );
  return match?.[1];
}

function motionPreviewDocument(
  html: string,
  keepInsideViewport: boolean,
): string {
  const safetyStyle = keepInsideViewport
    ? `<style data-qwenpaw-viewport-safety>html{padding:5%!important;box-sizing:border-box!important;overflow:hidden!important}body{width:100%!important;height:100%!important;box-sizing:border-box!important;overflow:visible!important;transform:scale(.9)!important;transform-origin:center!important}p,[class*=text],[class*=title],[class*=caption]{max-width:100%!important;font-size:min(18vh,20vw)!important;line-height:1.15!important;white-space:normal!important;overflow-wrap:anywhere!important;word-break:break-word!important;letter-spacing:.02em!important;-webkit-text-stroke:0!important;text-shadow:1px 1px 0 rgba(0,0,0,.22)!important}[data-motion-motif=caption_card] [class*=text]{font-size:min(25vh,30vw)!important;line-height:1.08!important;max-height:100%!important}${pawTrailCompatibilityCss()}</style>`
    : `<style data-qwenpaw-motion-compat>${pawTrailCompatibilityCss()}</style>`;
  return /<\/head>/i.test(html)
    ? html.replace(/<\/head>/i, `${safetyStyle}</head>`)
    : `${safetyStyle}${html}`;
}

function pawTrailCompatibilityCss(): string {
  return "[data-motion-motif=paw_trail] .p4,[data-motion-motif=paw_trail] .p5{display:none!important}[data-motion-motif=paw_trail] .toe{width:20%!important;height:20%!important}[data-motion-motif=paw_trail] .t1{left:2%!important;top:28%!important}[data-motion-motif=paw_trail] .t2{left:27%!important;top:7%!important}[data-motion-motif=paw_trail] .t3{left:auto!important;right:27%!important;top:3%!important}[data-motion-motif=paw_trail] .t4{left:auto!important;right:2%!important;top:24%!important}[data-motion-motif=paw_trail] .p1,[data-motion-motif=paw_trail] .p2,[data-motion-motif=paw_trail] .p3{opacity:0;animation:qwenpaw-paw-appear .36s cubic-bezier(.2,.85,.2,1) forwards!important}[data-motion-motif=paw_trail] .p1{animation-delay:.08s!important}[data-motion-motif=paw_trail] .p2{animation-delay:.38s!important}[data-motion-motif=paw_trail] .p3{animation-delay:.68s!important}[data-motion-motif=alert_mark] .bar{top:29%!important;height:29%!important}[data-motion-motif=alert_mark] .dot{left:45%!important;top:62%!important;width:10%!important}@keyframes qwenpaw-paw-appear{0%{opacity:0}100%{opacity:1}}";
}

function hasMotionDocument(
  motion: MotionGraphicDocument | null | undefined,
): motion is MotionGraphicDocument {
  return Boolean(motion && (motion.html || motion.html_file_id));
}

/** Stable content identity for one motion document (inline or externalized). */
function motionDocumentKey(motion: MotionGraphicDocument): string {
  return motion.html_file_id ?? motion.html ?? "";
}

function motionMotif(
  motion: MotionGraphicDocument,
  html: string | null,
): string | undefined {
  if (typeof motion.motif === "string" && motion.motif) return motion.motif;
  return html ? motionDataSetting(html, "motif") : undefined;
}

/** Resolve the document body: inline directly, externalized via fetch. */
function useMotionDocumentHtml(motion: MotionGraphicDocument | null): {
  html: string | null;
  failed: boolean;
} {
  const inline = motion?.html ?? null;
  const fileId = motion?.html_file_id ?? null;
  const [fetched, setFetched] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (inline || !fileId) return undefined;
    let cancelled = false;
    setFetched(null);
    setFailed(false);
    fetchMotionDocument(fileId)
      .then((text) => {
        if (!cancelled) setFetched(text);
      })
      .catch(() => {
        // Fail open: an unreachable externalized body must release the
        // readiness gate instead of pinning the preview notice forever.
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [fileId, inline]);
  if (inline) return { html: inline, failed: false };
  return { html: fileId ? fetched : null, failed };
}

function MotionOverlayLayer({
  layer,
  playheadTick,
  ticksPerSecond,
  playing,
  visualKey,
  onVisualReadyChange,
}: {
  layer: ElementPlayback;
  playheadTick: number;
  ticksPerSecond: number;
  playing: boolean;
  visualKey: string;
  onVisualReadyChange: (visualKey: string, ready: boolean) => void;
}) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const { t } = useTranslation();
  const { element } = layer;
  const motion =
    element.creation.type === "overlay" ? element.creation.motion : null;
  // js-timeline documents never execute in the preview (the iframe
  // sandbox forbids scripts and vendored runtimes cannot resolve from
  // srcDoc); a backend-rendered settled poster stands in instead, and
  // readiness comes from that real image load. Inline html_js bodies
  // cannot exist in committed Projects (the schema rejects them), so
  // the poster is the only html_js preview surface.
  const isJsTimeline = motion?.format === "html_js";
  const posterFileId = isJsTimeline ? motion?.html_file_id ?? null : null;
  const [posterFailed, setPosterFailed] = useState(false);
  const { html, failed: htmlFailed } = useMotionDocumentHtml(
    isJsTimeline ? null : motion ?? null,
  );
  const isTextOverlay =
    element.creation.type === "overlay" &&
    overlayContentKind(element.creation) === "copy" &&
    Boolean(element.creation.text.trim());
  const localTimeMs =
    (Math.max(0, playheadTick - element.span.start_tick) / ticksPerSecond) *
    1000;
  // While playing, CSS animations advance on their own after one alignment.
  // Paused scrubbing still needs every playhead change reflected immediately.
  const pausedSeekTimeMs = playing ? null : localTimeMs;
  const durationMs = (element.span.duration_tick / ticksPerSecond) * 1000;
  const exitStyle =
    motion?.exit ?? (html ? motionDataSetting(html, "exit") : undefined);
  const exitProgress = motionExitProgress(exitStyle, localTimeMs, durationMs);
  const boxStyle = locationBoxStyle(element.location);
  const exitScale = exitStyle === "shrink" ? 1 - exitProgress * 0.18 : 1;
  const baseOpacity =
    typeof boxStyle.opacity === "number" ? boxStyle.opacity : 1;

  const syncAnimations = () => {
    const document = iframeRef.current?.contentDocument;
    if (!document || typeof document.getAnimations !== "function") return;
    document.getAnimations().forEach((animation) => {
      syncMotionAnimation(animation, localTimeMs, playing);
    });
  };

  useEffect(syncAnimations, [playing, pausedSeekTimeMs]);
  useEffect(() => {
    return () => onVisualReadyChange(visualKey, false);
  }, [onVisualReadyChange, visualKey]);
  // A js timeline whose poster cannot be served fails closed: it
  // renders nothing but releases the readiness gate, because the
  // decoration is additive polish and may not hold the whole preview
  // hostage. Its document body never renders without the seek engine.
  useEffect(() => {
    if (isJsTimeline && (!posterFileId || posterFailed)) {
      onVisualReadyChange(visualKey, true);
    }
  }, [
    isJsTimeline,
    posterFileId,
    posterFailed,
    onVisualReadyChange,
    visualKey,
  ]);
  // An externalized html_css body whose fetch failed also fails open:
  // there is nothing to render, so it must not hold the preview hostage.
  useEffect(() => {
    if (!isJsTimeline && htmlFailed) {
      onVisualReadyChange(visualKey, true);
    }
  }, [isJsTimeline, htmlFailed, onVisualReadyChange, visualKey]);

  if (!motion) return null;
  if (isJsTimeline) {
    if (!posterFileId || posterFailed) return null;
    const motif = motionMotif(motion, null);
    if (motif && RETIRED_MOTION_MOTIFS.has(motif)) return null;
    return (
      <img
        data-live-motion-overlay={element.element_id}
        data-live-motion-poster="true"
        src={getMotionDocumentPosterUrl(
          posterFileId,
          Math.round(1280 * (element.location?.width ?? 1)),
          Math.round(720 * (element.location?.height ?? 1)),
        )}
        alt={element.label || "动态动效"}
        onLoad={() => onVisualReadyChange(visualKey, true)}
        onError={() => setPosterFailed(true)}
        className="pointer-events-none absolute border-0 bg-transparent"
        style={{
          ...boxStyle,
          opacity:
            exitStyle === "none"
              ? baseOpacity
              : baseOpacity * (1 - exitProgress),
          transform: `${boxStyle.transform ?? ""} scale(${exitScale})`.trim(),
        }}
      />
    );
  }
  if (!html) return null;
  const motif = motionMotif(motion, html);
  if (motif && RETIRED_MOTION_MOTIFS.has(motif)) return null;
  return (
    <iframe
      ref={iframeRef}
      data-live-motion-overlay={element.element_id}
      srcDoc={motionPreviewDocument(html, isTextOverlay)}
      title={element.label || t("livePreview.motionEffect")}
      // No scripts allowed; allow-same-origin exists only so the parent page
      // can sync the CSS animation timeline.
      sandbox="allow-same-origin"
      onLoad={() => {
        syncAnimations();
        onVisualReadyChange(visualKey, true);
      }}
      className="pointer-events-none absolute border-0 bg-transparent"
      style={{
        ...boxStyle,
        opacity:
          exitStyle === "none" ? baseOpacity : baseOpacity * (1 - exitProgress),
        transform: `${boxStyle.transform ?? ""} scale(${exitScale})`.trim(),
      }}
    />
  );
}

/**
 * Live-assembly preview: plays ready media directly in layers by each
 * element's span/z_index/location without waiting for final composition.
 * Whenever any visible layer is still generating, loading or seeking, an
 * opaque full-frame notice covers the pre-mounted background layers so users
 * never see a half-assembled frame with missing layers. Once a complete
 * frame has been painted, transient regressions (drift-correction seeks,
 * short buffer stalls) keep the last frame on screen and only surface the
 * notice when the gap persists beyond INCOMPLETE_NOTICE_DELAY_MS.
 */
export default function TimelineLivePreview({
  project,
  timeline,
  durationTick,
  playheadTick,
  playing,
  muted,
  tasks,
  onPlayheadChange,
  onPlayingChange,
}: TimelineLivePreviewProps) {
  const { t } = useTranslation();
  const ticksPerSecond = timeline.ticks_per_second || 1;
  const mediaRefs = useRef(new Map<string, HTMLVideoElement>());
  const imageRefs = useRef(new Map<string, HTMLImageElement>());
  const mediaRefCallbacks = useRef(
    new Map<string, (node: HTMLVideoElement | null) => void>(),
  );
  const imageRefCallbacks = useRef(
    new Map<string, (node: HTMLImageElement | null) => void>(),
  );
  const clock = useRef<{ baseTick: number; baseTime: number } | null>(null);
  const lastEmittedTick = useRef(playheadTick);
  const lastCorrectionSeekAt = useRef(new Map<string, number>());
  const stageRef = useRef<HTMLDivElement>(null);
  const [stageWidth, setStageWidth] = useState(1280);
  const [stageHeight, setStageHeight] = useState(720);
  const [visualRevision, setVisualRevision] = useState(0);
  const [readyMotionKeys, setReadyMotionKeys] = useState<Set<string>>(
    () => new Set(),
  );
  const refreshVisualReadiness = useCallback(
    () => setVisualRevision((revision) => revision + 1),
    [],
  );
  const handleMotionVisualReady = useCallback(
    (visualKey: string, ready: boolean) => {
      setReadyMotionKeys((current) => {
        if (current.has(visualKey) === ready) return current;
        const next = new Set(current);
        if (ready) next.add(visualKey);
        else next.delete(visualKey);
        return next;
      });
    },
    [],
  );

  useLayoutEffect(() => {
    const node = stageRef.current;
    if (!node) return;
    const update = () => {
      setStageWidth(Math.max(1, node.clientWidth));
      setStageHeight(Math.max(1, node.clientHeight));
    };
    update();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(update);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  // Same convention as final composition: audio elements don't participate
  // (only the main track's original sound is kept), so the live preview
  // neither renders nor plays them.
  const layers = useMemo(
    () =>
      playbackLayersInWindow(project, timeline, playheadTick, tasks).filter(
        (layer) => layer.element.creation.type !== "audio",
      ),
    [playheadTick, project, tasks, timeline],
  );
  const visibleLayers = useMemo(
    () =>
      layers.filter((layer) => {
        const { span } = layer.element;
        return (
          span.start_tick <= playheadTick &&
          playheadTick < span.start_tick + span.duration_tick
        );
      }),
    [layers, playheadTick],
  );
  const visibleIds = useMemo(
    () => new Set(visibleLayers.map((layer) => layer.element.element_id)),
    [visibleLayers],
  );

  // rAF master clock: while playing, advance the playhead by real elapsed
  // time; video layers only follow and correct drift.
  useEffect(() => {
    if (!playing) {
      clock.current = null;
      return;
    }
    let frame = 0;
    const step = (now: number) => {
      if (!clock.current) {
        clock.current = { baseTick: lastEmittedTick.current, baseTime: now };
      }
      const tick = Math.round(
        clock.current.baseTick +
          ((now - clock.current.baseTime) / 1000) * ticksPerSecond,
      );
      if (tick >= durationTick) {
        lastEmittedTick.current = durationTick;
        onPlayheadChange(durationTick);
        onPlayingChange(false);
        return;
      }
      lastEmittedTick.current = tick;
      onPlayheadChange(tick);
      frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing, durationTick, ticksPerSecond]);

  // Re-base the clock when an external scrub happens (clicking the timeline or
  // progress bar).
  useEffect(() => {
    if (Math.abs(playheadTick - lastEmittedTick.current) <= 1) return;
    lastEmittedTick.current = playheadTick;
    clock.current = null;
  }, [playheadTick]);

  // Keep every mounted media layer following the playhead: play when visible,
  // pause when out of range, correct when drifting.
  useEffect(() => {
    layers.forEach((layer) => {
      if (!layer.media || layer.media.mediaKind === "image") return;
      const media = mediaRefs.current.get(layer.element.element_id);
      if (!media) return;
      const target = mediaTargetSeconds(layer, playheadTick, ticksPerSecond);
      const visible = visibleIds.has(layer.element.element_id);

      // Check if playhead is beyond source material duration
      const sourceWindowSeconds =
        layer.media.sourceOutSeconds != null
          ? layer.media.sourceOutSeconds - layer.media.sourceInSeconds
          : layer.media.durationSeconds;
      const effectiveWindowSeconds = Math.min(
        sourceWindowSeconds ?? Infinity,
        layer.media.durationSeconds ?? Infinity,
      );
      const localSeconds =
        Math.max(0, playheadTick - layer.element.span.start_tick) /
        ticksPerSecond;
      const isBeyondSource = localSeconds > effectiveWindowSeconds;

      if (media.playbackRate !== layer.media.playbackRate) {
        media.playbackRate = layer.media.playbackRate;
      }

      if (!visible || !playing || isBeyondSource) {
        // Pause when beyond source duration, out of view, or not playing
        if (!media.paused) media.pause();
        if (visible && isBeyondSource) {
          // Freeze on the same last-window frame the readiness check
          // expects: mediaTargetSeconds already clamps to the window end
          // and includes the source-in offset. Writing a bare
          // window-relative time here (without source-in) left the
          // element seconds away from the drift target forever.
          const frozen = reachableTargetSeconds(target, media);
          if (Math.abs(media.currentTime - frozen) > 0.001) {
            media.currentTime = frozen;
          }
        } else if (
          !playing &&
          visible &&
          Math.abs(media.currentTime - reachableTargetSeconds(target, media)) >
            DRIFT_TOLERANCE_SECONDS
        ) {
          media.currentTime = reachableTargetSeconds(target, media);
        }
        return;
      }
      if (
        Math.abs(media.currentTime - reachableTargetSeconds(target, media)) >
        PLAYING_DRIFT_TOLERANCE_SECONDS
      ) {
        // Rate-limit correction seeks: each one flips the element into
        // `seeking` and repeated pull-backs on a slow decoder turned into a
        // visible stutter loop. The rAF clock keeps this effect running, so
        // a skipped correction is retried on a later frame.
        const now = performance.now();
        const lastSeek =
          lastCorrectionSeekAt.current.get(layer.element.element_id) ?? 0;
        if (!media.seeking && now - lastSeek >= PLAYING_SEEK_INTERVAL_MS) {
          lastCorrectionSeekAt.current.set(layer.element.element_id, now);
          media.currentTime = reachableTargetSeconds(target, media);
        }
      }
      if (media.paused) {
        media.play()?.catch(() => undefined);
      }
    });
  }, [layers, playheadTick, playing, ticksPerSecond, visibleIds]);

  // Stop on unmount: avoid leftover audio after the component is destroyed.
  useEffect(() => {
    const refs = mediaRefs.current;
    return () => refs.forEach((media) => media.pause());
  }, []);

  const registerMedia = useCallback(
    (elementId: string) => {
      let callback = mediaRefCallbacks.current.get(elementId);
      if (!callback) {
        callback = (node: HTMLVideoElement | null) => {
          if (node) mediaRefs.current.set(elementId, node);
          else mediaRefs.current.delete(elementId);
          refreshVisualReadiness();
        };
        mediaRefCallbacks.current.set(elementId, callback);
      }
      return callback;
    },
    [refreshVisualReadiness],
  );
  const registerImage = useCallback(
    (elementId: string) => {
      let callback = imageRefCallbacks.current.get(elementId);
      if (!callback) {
        callback = (node: HTMLImageElement | null) => {
          if (node) imageRefs.current.set(elementId, node);
          else imageRefs.current.delete(elementId);
          refreshVisualReadiness();
        };
        imageRefCallbacks.current.set(elementId, callback);
      }
      return callback;
    },
    [refreshVisualReadiness],
  );

  const anyVisible = visibleIds.size > 0;
  const semanticIncompleteLayers = useMemo(
    () =>
      visibleLayers.filter(
        (layer) => layer.status !== "ready" && layer.status !== "stale",
      ),
    [visibleLayers],
  );
  const visualIncompleteLayers = useMemo(
    () =>
      visibleLayers.filter((layer) => {
        if (layer.status !== "ready") return false;
        const { element, media } = layer;
        if (media?.mediaKind === "video") {
          const node = mediaRefs.current.get(element.element_id);
          if (!node || node.error || node.readyState < 2 || node.seeking)
            return true;
          if (playing) return false;
          return (
            Math.abs(
              node.currentTime -
                reachableTargetSeconds(
                  mediaTargetSeconds(layer, playheadTick, ticksPerSecond),
                  node,
                ),
            ) > DRIFT_TOLERANCE_SECONDS
          );
        }
        if (media?.mediaKind === "image") {
          const node = imageRefs.current.get(element.element_id);
          return !node?.complete || node.naturalWidth <= 0;
        }
        if (media) return true;
        if (
          element.creation.type === "overlay" &&
          hasMotionDocument(element.creation.motion)
        ) {
          const overlayMotion = element.creation.motion;
          const motif = motionMotif(overlayMotion, overlayMotion.html ?? null);
          if (motif && RETIRED_MOTION_MOTIFS.has(motif)) return false;
          return !readyMotionKeys.has(
            `${element.element_id}:${motionDocumentKey(overlayMotion)}`,
          );
        }
        return false;
      }),
    [
      playheadTick,
      playing,
      readyMotionKeys,
      ticksPerSecond,
      visibleLayers,
      visualRevision,
    ],
  );
  const previewIncomplete =
    anyVisible &&
    (semanticIncompleteLayers.length > 0 || visualIncompleteLayers.length > 0);
  const incompleteLayerCount = new Set(
    [...semanticIncompleteLayers, ...visualIncompleteLayers].map(
      (layer) => layer.element.element_id,
    ),
  ).size;

  // Debounced notice: a composite that was already complete keeps its last
  // painted frame during transient seeks/buffering instead of flashing the
  // opaque cover for a few frames. Semantic gaps (layers still generating)
  // and cold starts (nothing painted yet) cover immediately — a
  // half-assembled frame must never be presented as content.
  const hadCompleteFrame = useRef(false);
  const [noticeVisible, setNoticeVisible] = useState(true);
  const noticeImmediate =
    semanticIncompleteLayers.length > 0 || !hadCompleteFrame.current;
  useEffect(() => {
    if (!previewIncomplete) {
      if (anyVisible) hadCompleteFrame.current = true;
      setNoticeVisible(false);
      return;
    }
    if (noticeImmediate) {
      setNoticeVisible(true);
      return;
    }
    const timer = window.setTimeout(
      () => setNoticeVisible(true),
      INCOMPLETE_NOTICE_DELAY_MS,
    );
    return () => window.clearTimeout(timer);
  }, [anyVisible, noticeImmediate, previewIncomplete]);
  // First paint has no effect pass yet: fall back to the immediate rule so a
  // cold start is covered from the very first frame.
  const showIncompleteNotice =
    previewIncomplete && (noticeVisible || noticeImmediate);

  return (
    <div
      data-timeline-live-preview
      className="relative flex h-full w-full items-center justify-center"
    >
      <div
        ref={stageRef}
        data-live-stage
        className="relative max-h-full max-w-full overflow-hidden bg-black"
        style={{
          aspectRatio: aspectRatioStyle(project.settings.aspect_ratio),
          height: "100%",
        }}
      >
        {!anyVisible && (
          <div className="absolute inset-0 flex items-center justify-center text-sm text-white/55">
            {t("livePreview.noContentYet")}
          </div>
        )}
        {layers.map((layer) => {
          const { element, media, status } = layer;
          const elementId = element.element_id;
          const visible = visibleIds.has(elementId);
          // Within a transition window the "to" layer fades in, matching the
          // backend xfade composition.
          const transitionOpacity = transitionOpacityAtTick(
            timeline,
            element,
            playheadTick,
          );
          if (media && media.mediaKind === "video") {
            // Audio policy identical to the final render: only main-track video
            // keeps its original sound, overlay media is muted.
            const silent = muted || element.creation.type === "overlay";
            const boxStyle = locationBoxStyle(element.location);
            const baseOpacity =
              typeof boxStyle.opacity === "number" ? boxStyle.opacity : 1;
            return (
              <video
                key={`${elementId}:${media.versionId}`}
                ref={registerMedia(elementId)}
                data-live-layer={elementId}
                data-live-layer-state={status}
                src={media.url}
                className={`absolute object-contain ${
                  visible ? "" : "invisible"
                }`}
                style={{
                  ...boxStyle,
                  opacity: baseOpacity * transitionOpacity,
                }}
                muted={silent}
                loop={media.loop}
                playsInline
                preload="auto"
                onLoadedData={refreshVisualReadiness}
                onCanPlay={refreshVisualReadiness}
                onSeeking={refreshVisualReadiness}
                onSeeked={refreshVisualReadiness}
                onWaiting={refreshVisualReadiness}
                onStalled={refreshVisualReadiness}
                onEmptied={refreshVisualReadiness}
                onError={refreshVisualReadiness}
              />
            );
          }
          if (!visible) return null;
          if (media && media.mediaKind === "image") {
            const boxStyle = locationBoxStyle(element.location);
            const baseOpacity =
              typeof boxStyle.opacity === "number" ? boxStyle.opacity : 1;
            return (
              <img
                key={`${elementId}:${media.versionId}`}
                ref={registerImage(elementId)}
                data-live-layer={elementId}
                data-live-layer-state={status}
                src={media.url}
                alt={element.label || elementId}
                className="absolute object-contain"
                style={{
                  ...boxStyle,
                  opacity: baseOpacity * transitionOpacity,
                }}
                onLoad={refreshVisualReadiness}
                onError={refreshVisualReadiness}
              />
            );
          }
          if (status === "ready") {
            if (
              element.creation.type === "overlay" &&
              hasMotionDocument(element.creation.motion)
            ) {
              return (
                <MotionOverlayLayer
                  key={elementId}
                  layer={layer}
                  playheadTick={playheadTick}
                  ticksPerSecond={ticksPerSecond}
                  playing={playing}
                  visualKey={`${elementId}:${motionDocumentKey(
                    element.creation.motion,
                  )}`}
                  onVisualReadyChange={handleMotionVisualReady}
                />
              );
            }
            return (
              <TextOverlayLayer
                key={elementId}
                layer={layer}
                stageWidth={stageWidth}
                stageHeight={stageHeight}
              />
            );
          }
          return <PlaceholderLayer key={elementId} layer={layer} />;
        })}
        {showIncompleteNotice && (
          <div
            data-live-preview-incomplete
            role="status"
            aria-live="polite"
            className="absolute inset-0 z-20 flex flex-col items-center justify-center gap-2 bg-[radial-gradient(circle_at_center,#2b2521_0,#161210_62%,#0d0b0a_100%)] px-6 text-center"
          >
            <Loader2 className="h-7 w-7 animate-spin text-white/75" />
            <span className="text-sm font-semibold text-white/90">
              {semanticIncompleteLayers.length > 0
                ? t("livePreview.notRenderedYet")
                : t("livePreview.locating")}
            </span>
            <span className="max-w-md text-xs leading-5 text-white/60">
              {semanticIncompleteLayers.length > 0
                ? `${incompleteLayerCount} ${t("livePreview.layersGenerating")}`
                : t("livePreview.loadingFrame")}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
