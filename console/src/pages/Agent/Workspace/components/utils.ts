import dayjs from "dayjs";

export const formatFileSize = (bytes: number): string => {
  if (bytes === 0) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
};

export const formatTimeAgo = (timestamp: number | string): string => {
  const time =
    typeof timestamp === "string" ? new Date(timestamp).getTime() : timestamp;
  if (isNaN(time)) return "-";

  return dayjs(time).fromNow();
};

export const isDailyMemoryFile = (filename: string): boolean => {
  return /^\d{4}-\d{2}-\d{2}\.md$/.test(filename);
};
