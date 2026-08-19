import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

export type AssetPreviewState =
  | "planned"
  | "processing"
  | "ready"
  | "failed"
  | "unavailable";

function placeholderLabel(
  state: AssetPreviewState,
  loadFailed: boolean,
  t: (key: string) => string,
): string {
  if (loadFailed) return t("assetPreview.previewUnavailable");
  if (state === "planned") return t("assetPreview.pendingGeneration");
  if (state === "processing") return t("assetPreview.ingesting");
  if (state === "failed") return t("assetPreview.ingestFailed");
  return t("assetPreview.noPreview");
}

// Audio has no visual frame to show, so a ready track renders as a
// deterministic waveform silhouette (seeded by name) instead of a blank
// placeholder; the same green as the timeline audio track keeps the two
// surfaces reading as one media kind.
const WAVEFORM_BARS = 28;

function waveformHeights(seedText: string): number[] {
  let seed = 2166136261;
  for (let i = 0; i < seedText.length; i += 1) {
    seed = Math.imul(seed ^ seedText.charCodeAt(i), 16777619);
  }
  const heights: number[] = [];
  for (let i = 0; i < WAVEFORM_BARS; i += 1) {
    seed = Math.imul(seed ^ (seed >>> 13), 1274126177);
    const noise = ((seed >>> 8) % 1000) / 1000;
    const envelope = Math.sin((Math.PI * (i + 1)) / (WAVEFORM_BARS + 1));
    heights.push(0.18 + 0.72 * noise * (0.35 + 0.65 * envelope));
  }
  return heights;
}

function AudioWaveformPreview({ name }: { name: string }) {
  const heights = waveformHeights(name);
  return (
    <span
      data-asset-preview-kind="audio-waveform"
      aria-label={`${name} 音频`}
      className="flex h-full w-full items-center justify-center gap-[2px] px-3"
    >
      {heights.map((height, index) => (
        <i
          key={index}
          className="w-[3px] shrink-0 rounded-full"
          style={{
            height: `${Math.round(height * 62)}%`,
            background: "#12b76a",
            opacity: 0.85,
          }}
        />
      ))}
    </span>
  );
}

export default function AssetMediaPreview({
  name,
  mediaType,
  previewUrl,
  state,
  controls = false,
  mediaClassName,
  placeholderClassName,
}: {
  name: string;
  mediaType: string;
  previewUrl?: string;
  state: AssetPreviewState;
  controls?: boolean;
  mediaClassName: string;
  placeholderClassName: string;
}) {
  const [loadFailed, setLoadFailed] = useState(false);
  const { t } = useTranslation();

  useEffect(() => setLoadFailed(false), [previewUrl]);

  const canRender = state === "ready" && Boolean(previewUrl) && !loadFailed;
  if (canRender && mediaType === "video") {
    return (
      <video
        src={previewUrl}
        aria-label={`${name} ${t("assetPreview.video")}`}
        controls={controls}
        muted={!controls}
        playsInline
        preload="metadata"
        onError={() => setLoadFailed(true)}
        className={mediaClassName}
      />
    );
  }
  if (canRender && mediaType === "image") {
    return (
      <img
        src={previewUrl}
        alt={name}
        onError={() => setLoadFailed(true)}
        className={mediaClassName}
      />
    );
  }
  if (mediaType === "audio" && state === "ready" && !loadFailed) {
    return <AudioWaveformPreview name={name} />;
  }
  return (
    <span
      data-asset-preview-state={loadFailed ? "unavailable" : state}
      className={placeholderClassName}
    >
      {placeholderLabel(state, loadFailed, t)}
    </span>
  );
}
