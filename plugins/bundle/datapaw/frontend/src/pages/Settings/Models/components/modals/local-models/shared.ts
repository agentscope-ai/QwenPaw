import prettyBytes from "pretty-bytes";
import type { LocalDownloadProgress } from "../../../../../../api/types";

export function isDownloadActive(
  progress: LocalDownloadProgress | null,
): boolean {
  return (
    progress?.status === "pending" ||
    progress?.status === "downloading" ||
    progress?.status === "canceling"
  );
}

export function getProgressPercent(
  progress: LocalDownloadProgress | null,
): number | null {
  if (!progress?.total_bytes || progress.total_bytes <= 0) {
    return null;
  }
  return Math.min(
    100,
    Math.round((progress.downloaded_bytes / progress.total_bytes) * 100),
  );
}

export function formatProgressText(
  progress: LocalDownloadProgress | null,
): string {
  if (!progress) {
    return "";
  }

  const percent = getProgressPercent(progress);
  if (percent === null) {
    return `${prettyBytes(progress.downloaded_bytes)}`;
  }

  return `${percent}% · ${prettyBytes(
    progress.downloaded_bytes,
  )} / ${prettyBytes(progress.total_bytes || 0)}`;
}
