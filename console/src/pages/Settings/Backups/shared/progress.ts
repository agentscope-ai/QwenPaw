/**
 * Pure helper that converts backup job snapshots into UI state
 * (percent + status message). Kept separate from the React component so any
 * hook can consume it without importing a component tree.
 */
import type {
  BackupJobSnapshot,
  BackupProgressEvent,
} from "@/api/types/backup";

/**
 * Maps one legacy SSE event to { progress (0-100), msg }.
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

/**
 * Maps one current job snapshot to { progress (0-100), msg }.
 */
export function handleBackupJobSnapshot(
  snapshot: BackupJobSnapshot,
  t: (key: string, params?: Record<string, unknown>) => string,
): { progress: number; msg: string } {
  if (snapshot.status === "completed") {
    return { progress: 100, msg: t("backup.progressDone") };
  }
  if (snapshot.phase === "finalizing") {
    return {
      progress: snapshot.percent,
      msg: t("backup.progressSaving"),
    };
  }
  if (snapshot.current_agent) {
    return {
      progress: snapshot.percent,
      msg: t("backup.progressAgent", {
        index: snapshot.agent_index + 1,
        total: snapshot.total_agents,
      }),
    };
  }
  return { progress: snapshot.percent, msg: t("backup.progressStarting") };
}
