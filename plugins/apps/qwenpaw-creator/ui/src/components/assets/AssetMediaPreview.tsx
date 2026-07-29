import { useEffect, useState } from "react";

export type AssetPreviewState =
  | "planned"
  | "processing"
  | "ready"
  | "failed"
  | "unavailable";

function placeholderLabel(
  state: AssetPreviewState,
  loadFailed: boolean,
): string {
  if (loadFailed) return "预览不可用";
  if (state === "planned") return "待生成";
  if (state === "processing") return "入库中";
  if (state === "failed") return "入库失败";
  return "暂无预览";
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

  useEffect(() => setLoadFailed(false), [previewUrl]);

  const canRender = state === "ready" && Boolean(previewUrl) && !loadFailed;
  if (canRender && mediaType === "video") {
    return (
      <video
        src={previewUrl}
        aria-label={`${name} 视频`}
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
  return (
    <span
      data-asset-preview-state={loadFailed ? "unavailable" : state}
      className={placeholderClassName}
    >
      {placeholderLabel(state, loadFailed)}
    </span>
  );
}
