import type { ChatSpec } from "../../../../api/types";

export interface Session extends ChatSpec {
  name?: string;
}

/**
 * Format timestamp for display in user's local timezone.
 * Backend should send timezone-aware ISO strings (e.g., "2026-08-01T10:36:39+08:00")
 * after the fix in #6301. This function parses them correctly without forcing UTC.
 */
export const formatTime = (timestamp: string | number | null): string => {
  if (timestamp === null || timestamp === undefined) return "N/A";
  const date = new Date(
    typeof timestamp === "string" ? timestamp : timestamp,
  );
  if (isNaN(date.getTime())) return "N/A";
  return date.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
};