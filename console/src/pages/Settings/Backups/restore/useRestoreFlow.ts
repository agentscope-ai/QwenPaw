import { useState } from "react";
import type { BackupMeta } from "@/api/types/backup";

/**
 * Manages the restore flow state machine:
 *   1. handleRestore(backup) → opens PreRestoreConfirmModal
 *   2. confirmRestoreWithoutBackup → opens the impact preview. The server
 *      creates its mandatory protection backup immediately before restore.
 */
export function useRestoreFlow() {
  const [preRestoreConfirmTarget, setPreRestoreConfirmTarget] =
    useState<BackupMeta | null>(null);
  const [restoreTarget, setRestoreTarget] = useState<BackupMeta | null>(null);

  /** Entry point — records which backup the user wants to restore and opens the pre-restore confirm dialog. */
  const handleRestore = (backup: BackupMeta) => {
    setPreRestoreConfirmTarget(backup);
  };

  /** User chose to skip the pre-restore snapshot; go straight to RestoreBackupModal. */
  const confirmRestoreWithoutBackup = (target: BackupMeta) => {
    setPreRestoreConfirmTarget(null);
    setRestoreTarget(target);
  };

  /** User cancelled the pre-restore confirm dialog without proceeding. */
  const cancelPreRestore = () => setPreRestoreConfirmTarget(null);

  return {
    preRestoreConfirmTarget,
    restoreTarget,
    setRestoreTarget,
    handleRestore,
    confirmRestoreWithoutBackup,
    cancelPreRestore,
  };
}
