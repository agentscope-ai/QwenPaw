/**
 * Pure helper that converts raw SSE backup progress events into UI state
 * (percent + status message). Kept separate from the React component so any
 * hook can consume it without importing a component tree.
 */
import type { BackupProgressEvent } from "@/api/types/backup";

/**
 * Maps a single SSE event to { progress (0-100), msg }.
 * Called by useBackupRunner on every streamed chunk.
 */
export function handleBackupProgressEvent(
  event: BackupProgressEvent,
  t: (key: string, params?: Record<string, unknown>) => string,
): { progress: number; msg: string } {
  switch (event.type) {
    case "start":
      return { progress: 0, msg: t("backup.progressStarting") };
    case "agent":
      return {
        progress: event.percent,
        msg: t("backup.progressAgent", {
          index: event.index + 1,
          total: event.total,
        }),
      };
    case "saving":
      return { progress: event.percent, msg: t("backup.progressSaving") };
    case "done":
      return { progress: 100, msg: t("backup.progressDone") };
    default:
      return { progress: 0, msg: "" };
  }
}
