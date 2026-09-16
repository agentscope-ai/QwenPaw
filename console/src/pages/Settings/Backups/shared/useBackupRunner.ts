/**
 * Shared hook that starts and observes an application-owned backup job.
 */
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import api from "@/api";
import { useAppMessage } from "@/hooks/useAppMessage";
import type {
  BackupJobSnapshot,
  CreateBackupRequest,
} from "@/api/types/backup";
import { handleBackupJobSnapshot } from "./progress";

interface UseBackupRunnerOptions {
  onSuccess?: () => void;
  onClose?: () => void;
}

/**
 * Transport abort only detaches the observer. Cancellation is always an
 * explicit job API request.
 */
export function useBackupRunner({
  onSuccess,
  onClose,
}: UseBackupRunnerOptions) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [progressMsg, setProgressMsg] = useState("");
  const abortControllerRef = useRef<AbortController | null>(null);
  const jobIdRef = useRef<string | null>(null);
  const cancelRequestedRef = useRef(false);

  const applySnapshot = (snapshot: BackupJobSnapshot) => {
    const { progress: nextProgress, msg } = handleBackupJobSnapshot(
      snapshot,
      t,
    );
    setProgress(nextProgress);
    setProgressMsg(msg);
  };

  const isTerminal = (snapshot: BackupJobSnapshot) =>
    ["completed", "failed", "cancelled"].includes(snapshot.status);

  const observeUntilTerminal = async (initial: BackupJobSnapshot) => {
    let latest = initial;
    let consecutiveStatusFailures = 0;
    applySnapshot(latest);

    while (!isTerminal(latest)) {
      const controller = new AbortController();
      abortControllerRef.current = controller;
      try {
        await api.streamBackupJob(
          latest.job_id,
          (snapshot) => {
            latest = snapshot;
            applySnapshot(snapshot);
          },
          controller.signal,
        );
      } catch (err) {
        if (err instanceof Error && err.name === "AbortError") throw err;
      } finally {
        if (abortControllerRef.current === controller) {
          abortControllerRef.current = null;
        }
      }

      if (isTerminal(latest)) break;
      try {
        latest = await api.getBackupJob(latest.job_id);
        consecutiveStatusFailures = 0;
        applySnapshot(latest);
      } catch (err) {
        consecutiveStatusFailures += 1;
        if (consecutiveStatusFailures >= 5) throw err;
      }

      if (!isTerminal(latest)) {
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
      }
    }
    return latest;
  };

  /** Resets visual progress state; called when the modal reopens for a fresh session. */
  const reset = () => {
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
    jobIdRef.current = null;
    cancelRequestedRef.current = false;
    setLoading(false);
    setProgress(0);
    setProgressMsg("");
  };

  const execute = async (getInitial: () => Promise<BackupJobSnapshot>) => {
    setLoading(true);
    setProgress(0);
    setProgressMsg(t("backup.progressStarting"));

    try {
      const initial = await getInitial();
      jobIdRef.current = initial.job_id;
      if (cancelRequestedRef.current) {
        try {
          await api.cancelBackupJob(initial.job_id);
        } catch (err) {
          cancelRequestedRef.current = false;
          throw err;
        }
        onClose?.();
        return;
      }

      const terminal = await observeUntilTerminal(initial);
      if (terminal.status === "failed") {
        throw new Error(terminal.error || "Backup failed");
      }
      if (terminal.status === "cancelled") {
        onClose?.();
        return;
      }
      message.success(t("backup.createSuccess"));
      onSuccess?.();
      onClose?.();
    } catch (err) {
      if (
        cancelRequestedRef.current ||
        (err instanceof Error && err.name === "AbortError")
      ) {
        return;
      }
      message.error(t("backup.createFailed"));
    } finally {
      setLoading(false);
      abortControllerRef.current = null;
      jobIdRef.current = null;
    }
  };

  const start = (data: CreateBackupRequest) =>
    execute(async () => {
      try {
        return await api.startBackupJob(data);
      } catch (err) {
        const active = await api.getActiveBackupJob();
        if (active) return active;
        throw err;
      }
    });

  const resume = (snapshot: BackupJobSnapshot) =>
    execute(() => Promise.resolve(snapshot));

  const cancel = async () => {
    cancelRequestedRef.current = true;
    const jobId = jobIdRef.current;
    if (!jobId) return;
    try {
      await api.cancelBackupJob(jobId);
      abortControllerRef.current?.abort();
      reset();
      onClose?.();
    } catch {
      cancelRequestedRef.current = false;
      message.error(t("backup.createFailed"));
    }
  };

  return { loading, progress, progressMsg, start, resume, cancel, reset };
}
