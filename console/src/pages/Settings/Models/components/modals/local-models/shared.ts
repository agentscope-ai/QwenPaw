import type { LocalDownloadProgress } from "../../../../../../api/types";

export function formatFileSize(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, index)).toFixed(1)} ${units[index]}`;
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
    return `${formatFileSize(progress.downloaded_bytes)}`;
  }

  return `${percent}% · ${formatFileSize(
    progress.downloaded_bytes,
  )} / ${formatFileSize(progress.total_bytes || 0)}`;
}
