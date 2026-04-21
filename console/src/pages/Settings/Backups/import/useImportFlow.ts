/**
 * Hook that owns the full import-backup flow:
 *   1. handleImport(file)      — uploads the zip; on 409 stores the conflict token.
 *   2. handleConflictChoice()  — confirms overwrite and retries with the stored token.
 *   3. clearConflict()         — dismisses the conflict modal without resolving.
 *
 * Kept separate from useRestoreFlow so each hook has a single responsibility.
 */
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import api from "@/api";
import { useAppMessage } from "@/hooks/useAppMessage";
import type { BackupConflictResponse, BackupMeta } from "@/api/types/backup";

interface UseImportFlowOptions {
  onSuccess: () => void;
}

export function useImportFlow({ onSuccess }: UseImportFlowOptions) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [conflictMeta, setConflictMeta] = useState<BackupMeta | null>(null);
  const pendingTokenRef = useRef<string | null>(null);

  /** Uploads the zip file. On HTTP 409, surfaces the conflict for user resolution. */
  const handleImport = async (file: File) => {
    try {
      await api.importBackup(file);
      message.success(t("backup.importSuccess"));
      onSuccess();
    } catch (err: unknown) {
      const conflict = (err as { conflict?: BackupConflictResponse }).conflict;
      if (conflict?.detail === "backup_conflict") {
        pendingTokenRef.current = conflict.pending_token;
        setConflictMeta(conflict.existing);
      } else {
        message.error(t("backup.importFailed"));
      }
    }
  };

  /** Re-submits the import using the pending token, confirming the overwrite. */
  const handleConflictChoice = async () => {
    const token = pendingTokenRef.current;
    setConflictMeta(null);
    pendingTokenRef.current = null;
    if (!token) return;
    try {
      await api.resolveImportConflict(token);
      message.success(t("backup.importSuccess"));
      onSuccess();
    } catch {
      message.error(t("backup.importFailed"));
    }
  };

  /** Discards the pending conflict token and closes the conflict modal. */
  const clearConflict = () => {
    setConflictMeta(null);
    pendingTokenRef.current = null;
  };

  return {
    conflictMeta,
    handleImport,
    handleConflictChoice,
    clearConflict,
  };
}
