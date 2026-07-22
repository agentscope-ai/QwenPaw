/**
 * Hook that owns the full import-backup flow:
 *   1. handleImport(file) uploads the zip; on 409 stores the conflict token.
 *   2. handleConflictChoice() confirms overwrite and retries with the stored token.
 *   3. clearConflict() dismisses the conflict modal without resolving.
 *
 * It also owns the foreign/legacy trust prompt. The first failed upload keeps
 * the File in memory; only after explicit confirmation do we retry with
 * trust_mode matching the prompt so the server can re-sign the archive
 * locally.
 *
 * Kept separate from useRestoreFlow so each hook has a single responsibility.
 */
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import api from "@/api";
import { useAppMessage } from "@/hooks/useAppMessage";
import type { BackupConflictResponse, BackupMeta } from "@/api/types/backup";
import { trustModeFromError, type BackupTrustMode } from "../trust/trustErrors";

interface UseImportFlowOptions {
  onSuccess: () => void;
}

type ImportTrustPrompt = {
  file: File;
  mode: BackupTrustMode;
};

export function useImportFlow({ onSuccess }: UseImportFlowOptions) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [conflictMeta, setConflictMeta] = useState<BackupMeta | null>(null);
  const [trustPrompt, setTrustPrompt] = useState<ImportTrustPrompt | null>(
    null,
  );
  const [trustLoading, setTrustLoading] = useState(false);
  const pendingTokenRef = useRef<string | null>(null);

  /** Uploads the zip file. On HTTP 409, surfaces conflict resolution. */
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
        const trustMode = trustModeFromError(err);
        if (trustMode) {
          setTrustPrompt({ file, mode: trustMode });
        } else {
          message.error(t("backup.importFailed"));
        }
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

  /** Retries the held upload after the user explicitly trusts the archive. */
  const handleTrustConfirm = async () => {
    if (!trustPrompt) return;
    setTrustLoading(true);
    try {
      await api.importBackup(trustPrompt.file, {
        trustMode: trustPrompt.mode,
      });
      message.success(t("backup.importSuccess"));
      setTrustPrompt(null);
      onSuccess();
    } catch (err: unknown) {
      const conflict = (err as { conflict?: BackupConflictResponse }).conflict;
      if (conflict?.detail === "backup_conflict") {
        pendingTokenRef.current = conflict.pending_token;
        setConflictMeta(conflict.existing);
        setTrustPrompt(null);
      } else {
        message.error(t("backup.importFailed"));
      }
    } finally {
      setTrustLoading(false);
    }
  };

  const clearTrust = () => setTrustPrompt(null);

  return {
    conflictMeta,
    trustFileName: trustPrompt?.file.name ?? null,
    trustMode: trustPrompt?.mode ?? null,
    trustLoading,
    handleImport,
    handleConflictChoice,
    handleTrustConfirm,
    clearConflict,
    clearTrust,
  };
}
