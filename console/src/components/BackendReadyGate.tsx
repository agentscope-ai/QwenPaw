import { useState, useEffect, useRef, useCallback, type ReactNode } from "react";
import BackendLoadingPage from "./BackendLoadingPage";

const API_BASE_URL = typeof import.meta.env.VITE_API_BASE_URL !== "undefined" ? import.meta.env.VITE_API_BASE_URL : "";
const POLL_INTERVAL = 1000;
const POLL_TIMEOUT = 120;
const REQUEST_TIMEOUT = 5000;

interface Props {
  children: ReactNode;
}

export default function BackendReadyGate({ children }: Props) {
  const [status, setStatus] = useState<"checking" | "ready" | "timeout">("checking");
  const [elapsed, setElapsed] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const mountedRef = useRef(true);

  const startPolling = useCallback(() => {
    setStatus("checking");
    setElapsed(0);

    const start = Date.now();

    const poll = async () => {
      try {
        const controller = new AbortController();
        const tid = setTimeout(() => controller.abort(), REQUEST_TIMEOUT);
        const res = await fetch(`${API_BASE_URL}/api/version`, {
          signal: controller.signal,
        });
        clearTimeout(tid);
        if (mountedRef.current && res.ok) {
          setStatus("ready");
          return;
        }
      } catch {
        // backend not ready yet
      }

      if (!mountedRef.current) return;
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

  useEffect(() => {
    // Browser mode: pass through immediately
    if (!API_BASE_URL) return;

    mountedRef.current = true;
    startPolling();

    return () => {
      mountedRef.current = false;
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }
    };
  }, [startPolling]);

  // Browser mode or backend ready
  if (!API_BASE_URL || status === "ready") {
    return <>{children}</>;
  }

  return (
    <BackendLoadingPage
      status={status}
      elapsed={elapsed}
      onRetry={startPolling}
    />
  );
}
