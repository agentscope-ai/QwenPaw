/**
 * Shared hook that drives the SSE backup-creation stream.
 * Owns progress/loading/abort state so both CreateBackupModal (user-initiated)
 * and SilentBackupModal (auto pre-restore) can share identical streaming logic.
 */
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import api from "@/api";
import { useAppMessage } from "@/hooks/useAppMessage";
import type { CreateBackupRequest } from "@/api/types/backup";
import { handleBackupProgressEvent } from "./progress";

interface UseBackupRunnerOptions {
  onSuccess?: () => void;
  onClose?: () => void;
}

/**
 * Returns { loading, progress, progressMsg, start, cancel, reset }.
 * - start(data): opens the SSE stream, updates progress state on every event.
 * - cancel():    aborts the in-flight request and resets state.
 * - reset():     clears progress/loading without aborting (used after modal reopens).
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

  /** Resets visual progress state; called when the modal reopens for a fresh session. */
  const reset = () => {
    setLoading(false);
    setProgress(0);
    setProgressMsg("");
  };

  /** Starts the backup stream. Resolves when the server sends the "done" event. */
  const start = async (data: CreateBackupRequest) => {
    const controller = new AbortController();
    abortControllerRef.current = controller;
    setLoading(true);
    setProgress(0);
    setProgressMsg(t("backup.progressStarting"));

    try {
      await api.createBackupStream(
        data,
        (event) => {
          const { progress: p, msg } = handleBackupProgressEvent(event, t);
          setProgress(p);
          setProgressMsg(msg);
        },
        controller.signal,
      );
      message.success(t("backup.createSuccess"));
      onSuccess?.();
      onClose?.();
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") return;
      message.error(t("backup.createFailed"));
    } finally {
      setLoading(false);
      abortControllerRef.current = null;
    }
  };

  /** Aborts the in-flight SSE request, resets state, and closes the modal. */
  const cancel = () => {
    abortControllerRef.current?.abort();
    reset();
    onClose?.();
  };

  return { loading, progress, progressMsg, start, cancel, reset };
}
