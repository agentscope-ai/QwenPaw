import {
  useState,
  useEffect,
  useRef,
  useCallback,
  type ReactNode,
} from "react";
import BackendLoadingPage from "./BackendLoadingPage";
import {
  getBackendStartupError,
  initRuntimeApiBaseUrl,
  isTauriRuntime,
  restartBackend,
} from "../api/config";

const POLL_INTERVAL = 1000;
const POLL_TIMEOUT = 180;
const REQUEST_TIMEOUT = 2500;

interface Props {
  children: ReactNode;
}

export default function BackendReadyGate({ children }: Props) {
  const [status, setStatus] = useState<
    "checking" | "ready" | "timeout" | "error"
  >("checking");
  const shouldGate = isTauriRuntime();
  const [elapsed, setElapsed] = useState(0);
  const [errorMessage, setErrorMessage] = useState("");
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const mountedRef = useRef(true);
  const pollRunRef = useRef(0);

  const startPolling = useCallback((apiBaseUrl: string) => {
    pollRunRef.current += 1;
    const runId = pollRunRef.current;
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    abortRef.current?.abort();
    abortRef.current = null;

    setStatus("checking");
    setElapsed(0);
    setErrorMessage("");

    const start = Date.now();

    const poll = async () => {
      try {
        const controller = new AbortController();
        abortRef.current = controller;
        const tid = setTimeout(() => controller.abort(), REQUEST_TIMEOUT);
        try {
          const res = await fetch(`${apiBaseUrl}/api/version`, {
            signal: controller.signal,
            cache: "no-store",
          });
          if (mountedRef.current && pollRunRef.current === runId && res.ok) {
            setStatus("ready");
            return;
          }
        } finally {
          clearTimeout(tid);
          if (abortRef.current === controller) {
            abortRef.current = null;
          }
        }
      } catch {
        // backend not ready yet
      }

      if (!mountedRef.current || pollRunRef.current !== runId) return;
      const startupError = await getBackendStartupError().catch(() => "");
      if (!mountedRef.current || pollRunRef.current !== runId) return;
      if (startupError) {
        setErrorMessage(startupError);
        setStatus("error");
        return;
      }
      const sec = Math.round((Date.now() - start) / 1000);
      setElapsed(sec);
      if (sec >= POLL_TIMEOUT) {
        setStatus("timeout");
        return;
      }
      timerRef.current = setTimeout(poll, POLL_INTERVAL);
    };

    poll();
  }, []);

  const retry = useCallback(() => {
    if (mountedRef.current) {
      setStatus("checking");
      setElapsed(0);
      setErrorMessage("");
    }
    restartBackend()
      .then((apiBaseUrl) => {
        if (!mountedRef.current) return;
        if (apiBaseUrl) {
          startPolling(apiBaseUrl);
        } else {
          setStatus("timeout");
        }
      })
      .catch(async () => {
        if (!mountedRef.current) return;
        const startupError = await getBackendStartupError().catch(() => "");
        if (!mountedRef.current) return;
        if (startupError) {
          setErrorMessage(startupError);
          setStatus("error");
        } else {
          setStatus("timeout");
        }
      });
  }, [startPolling]);

  useEffect(() => {
    // Browser mode: pass through immediately.
    if (!shouldGate) return;

    mountedRef.current = true;
    // In Tauri runtime isTauriRuntime() is true, so window.__TAURI__.core.invoke
    // is always available. initRuntimeApiBaseUrl() calls invoke("backend_port")
    // and resolves once Rust has initialized the backend port.
    initRuntimeApiBaseUrl()
      .then((apiBaseUrl) => {
        if (!mountedRef.current) return;
        startPolling(apiBaseUrl);
      })
      .catch(async () => {
        if (!mountedRef.current) return;
        const startupError = await getBackendStartupError().catch(() => "");
        if (!mountedRef.current) return;
        if (startupError) {
          setErrorMessage(startupError);
          setStatus("error");
        } else {
          setStatus("timeout");
        }
      });

    return () => {
      mountedRef.current = false;
      pollRunRef.current += 1;
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      abortRef.current?.abort();
      abortRef.current = null;
    };
  }, [shouldGate, startPolling]);

  // Browser mode or backend ready.
  if (!shouldGate || status === "ready") {
    return <>{children}</>;
  }

  return (
    <BackendLoadingPage
      status={status}
      elapsed={elapsed}
      totalSec={POLL_TIMEOUT}
      errorMessage={errorMessage}
      onRetry={retry}
    />
  );
}
