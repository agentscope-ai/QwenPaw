import { useState } from "react";
import type { BackupMeta } from "@/api/types/backup";

/**
 * Manages the restore flow state machine:
 *   1. handleRestore(backup) → opens PreRestoreConfirmModal
 *   2a. confirmRestoreWithoutBackup → opens RestoreBackupModal directly
 *   2b. confirmRestoreWithBackup    → opens SilentBackupModal first
 *   3. onPreRestoreBackupSuccess    → opens RestoreBackupModal after snapshot
 */
export function useRestoreFlow() {
  const [preRestoreConfirmTarget, setPreRestoreConfirmTarget] =
    useState<BackupMeta | null>(null);
  const [preRestoreBackupTarget, setPreRestoreBackupTarget] =
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

  /** User chose to take a pre-restore snapshot first; open SilentBackupModal. */
  const confirmRestoreWithBackup = (target: BackupMeta) => {
    setPreRestoreConfirmTarget(null);
    setPreRestoreBackupTarget(target);
  };

  /** User cancelled the pre-restore confirm dialog without proceeding. */
  const cancelPreRestore = () => setPreRestoreConfirmTarget(null);

  /** Called when the pre-restore snapshot finishes; advances to RestoreBackupModal. */
  const onPreRestoreBackupSuccess = () => {
    if (preRestoreBackupTarget) {
      setRestoreTarget(preRestoreBackupTarget);
    }
    setPreRestoreBackupTarget(null);
  };

  /** Called when SilentBackupModal is dismissed (e.g. user cancelled the snapshot). */
  const onPreRestoreBackupClose = () => {
    setPreRestoreBackupTarget(null);
  };

  return {
    preRestoreConfirmTarget,
    preRestoreBackupTarget,
    restoreTarget,
    setRestoreTarget,
    handleRestore,
    confirmRestoreWithoutBackup,
    confirmRestoreWithBackup,
    cancelPreRestore,
    onPreRestoreBackupSuccess,
    onPreRestoreBackupClose,
  };
}
