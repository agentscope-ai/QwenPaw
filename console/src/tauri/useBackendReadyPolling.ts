import { useCallback, useEffect, useRef, useState } from "react";
import {
  getBackendStartupError,
  initRuntimeApiBaseUrl,
  isTauriRuntime,
  restartBackend,
} from "./backendRuntime";

export type BackendReadyStatus = "checking" | "ready" | "timeout" | "error";

export const BACKEND_POLL_INTERVAL_MS = 1000;
export const BACKEND_POLL_TIMEOUT_SECONDS = 180;
export const BACKEND_REQUEST_TIMEOUT_MS = 2500;

interface BackendReadyPollingState {
  shouldGate: boolean;
  status: BackendReadyStatus;
  elapsed: number;
  totalSec: number;
  errorMessage: string;
  retry: () => void;
}

export default function useBackendReadyPolling(): BackendReadyPollingState {
  const shouldGate = isTauriRuntime();
  const [status, setStatus] = useState<BackendReadyStatus>("checking");
  const [elapsed, setElapsed] = useState(0);
  const [errorMessage, setErrorMessage] = useState("");
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

  const startPolling = useCallback(
    (apiBaseUrl: string) => {
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

      const start = Date.now();

      const poll = async () => {
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

        if (runRef.current !== runId) return;
        const startupError = await getBackendStartupError().catch(() => "");
        if (runRef.current !== runId) return;
        if (startupError) {
          setErrorMessage(startupError);
          setStatus("error");
          return;
        }

        const seconds = Math.round((Date.now() - start) / 1000);
        setElapsed(seconds);
        if (seconds >= BACKEND_POLL_TIMEOUT_SECONDS) {
          setStatus("timeout");
          return;
        }

        timer = setTimeout(poll, BACKEND_POLL_INTERVAL_MS);
      };

      void poll();
    },
    [cancelPolling],
  );

  const retry = useCallback(() => {
    cancelPolling();
    const runId = runRef.current;
    setStatus("checking");
    setElapsed(0);
    setErrorMessage("");

    restartBackend()
      .then((apiBaseUrl) => {
        if (runRef.current !== runId) return;
        if (apiBaseUrl) {
          startPolling(apiBaseUrl);
        } else {
          setStatus("timeout");
        }
      })
      .catch(() => {
        void showStartupFailure(runId);
      });
  }, [cancelPolling, showStartupFailure, startPolling]);

  useEffect(() => {
    if (!shouldGate) return undefined;

    cancelPolling();
    const runId = runRef.current;
    initRuntimeApiBaseUrl()
      .then((apiBaseUrl) => {
        if (runRef.current === runId) {
          startPolling(apiBaseUrl);
        }
      })
      .catch(() => {
        void showStartupFailure(runId);
      });

    return cancelPolling;
  }, [cancelPolling, shouldGate, showStartupFailure, startPolling]);

  return {
    shouldGate,
    status,
    elapsed,
    totalSec: BACKEND_POLL_TIMEOUT_SECONDS,
    errorMessage,
    retry,
  };
}
