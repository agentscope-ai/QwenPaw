import { useCallback, useEffect, useRef, useState } from "react";
import {
  backendConsoleUrl,
  getBackendStartupError,
  initRuntimeApiBaseUrl,
  restartBackend,
  shouldUseTauriStartupGate,
} from "./backendRuntime";

export type BackendReadyStatus = "checking" | "ready" | "timeout" | "error";

export const BACKEND_POLL_INTERVAL_MS = 1000;
export const BACKEND_POLL_TIMEOUT_SECONDS = 180;
export const BACKEND_REQUEST_TIMEOUT_MS = 2500;
export const BACKEND_STARTUP_ERROR_POLL_INTERVAL_MS = 3000;

interface BackendReadyPollingState {
  shouldGate: boolean;
  status: BackendReadyStatus;
  elapsed: number;
  totalSec: number;
  errorMessage: string;
  readyUrl: string;
  retry: () => void;
}

export default function useBackendReadyPolling(): BackendReadyPollingState {
  const shouldGate = shouldUseTauriStartupGate();
  const [status, setStatus] = useState<BackendReadyStatus>("checking");
  const [elapsed, setElapsed] = useState(0);
  const [errorMessage, setErrorMessage] = useState("");
  const [readyUrl, setReadyUrl] = useState("");
  const runRef = useRef(0);
  const cancelPollingRef = useRef<(() => void) | null>(null);

  const cancelPolling = useCallback(() => {
    runRef.current += 1;
    cancelPollingRef.current?.();
    cancelPollingRef.current = null;
  }, []);

  const showStartupFailure = useCallback(
    async (runId: number, fallbackStatus: BackendReadyStatus = "timeout") => {
      const startupError = await getBackendStartupError().catch(() => "");
      if (runRef.current !== runId) return;
      if (startupError) {
        setErrorMessage(startupError);
        setStatus("error");
      } else {
        setStatus(fallbackStatus);
      }
    },
    [],
  );

  const startPolling = useCallback(() => {
    cancelPolling();
    const runId = runRef.current;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let controller: AbortController | null = null;

    cancelPollingRef.current = () => {
      if (timer) {
        clearTimeout(timer);
        timer = null;
      }
      controller?.abort();
      controller = null;
    };

    setStatus("checking");
    setElapsed(0);
    setErrorMessage("");
    setReadyUrl("");

    const start = Date.now();
    let lastStartupErrorCheckAt = 0;

    const checkStartupError = async (): Promise<boolean> => {
      const startupError = await getBackendStartupError().catch(() => "");
      if (runRef.current !== runId) return true;
      if (!startupError) return false;

      setErrorMessage(startupError);
      setStatus("error");
      return true;
    };

    const poll = async () => {
      const apiBaseUrl = await initRuntimeApiBaseUrl().catch(() => "");
      if (runRef.current !== runId) return;

      if (apiBaseUrl) {
        try {
          controller = new AbortController();
          const timeoutId = setTimeout(
            () => controller?.abort(),
            BACKEND_REQUEST_TIMEOUT_MS,
          );
          try {
            const res = await fetch(`${apiBaseUrl}/api/version`, {
              signal: controller.signal,
              cache: "no-store",
            });
            if (runRef.current === runId && res.ok) {
              setReadyUrl(backendConsoleUrl(apiBaseUrl));
              setStatus("ready");
              return;
            }
          } finally {
            clearTimeout(timeoutId);
            controller = null;
          }
        } catch {
          // Backend not ready yet.
        }
      }

      if (runRef.current !== runId) return;
      const now = Date.now();
      const seconds = Math.round((now - start) / 1000);
      if (
        lastStartupErrorCheckAt === 0 ||
        now - lastStartupErrorCheckAt >= BACKEND_STARTUP_ERROR_POLL_INTERVAL_MS
      ) {
        lastStartupErrorCheckAt = now;
        if (await checkStartupError()) {
          return;
        }
      }

      if (runRef.current !== runId) return;
      setElapsed(seconds);
      if (seconds >= BACKEND_POLL_TIMEOUT_SECONDS) {
        if (await checkStartupError()) {
          return;
        }
        if (runRef.current !== runId) return;
        setStatus("timeout");
        return;
      }

      timer = setTimeout(poll, BACKEND_POLL_INTERVAL_MS);
    };

    void poll();
  }, [cancelPolling]);

  const retry = useCallback(() => {
    cancelPolling();
    const runId = runRef.current;
    setStatus("checking");
    setElapsed(0);
    setErrorMessage("");
    setReadyUrl("");

    restartBackend()
      .then(() => {
        if (runRef.current !== runId) return;
        startPolling();
      })
      .catch(() => {
        void showStartupFailure(runId);
      });
  }, [cancelPolling, showStartupFailure, startPolling]);

  useEffect(() => {
    if (!shouldGate) return undefined;

    startPolling();

    return cancelPolling;
  }, [cancelPolling, shouldGate, showStartupFailure, startPolling]);

  return {
    shouldGate,
    status,
    elapsed,
    totalSec: BACKEND_POLL_TIMEOUT_SECONDS,
    errorMessage,
    readyUrl,
    retry,
  };
}
