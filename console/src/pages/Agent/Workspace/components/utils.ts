import dayjs from "dayjs";

export const formatTimeAgo = (timestamp: number | string): string => {
  const time =
    typeof timestamp === "string" ? new Date(timestamp).getTime() : timestamp;
  if (isNaN(time)) return "-";

  return dayjs(time).fromNow();
};

export const isDailyMemoryFile = (filename: string): boolean => {
  return /^\d{4}-\d{2}-\d{2}\.md$/.test(filename);
};
