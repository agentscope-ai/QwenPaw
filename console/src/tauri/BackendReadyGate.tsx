import { type ReactNode, useEffect } from "react";
import BackendLoadingPage from "./BackendLoadingPage";
import useBackendReadyPolling from "./useBackendReadyPolling";

interface Props {
  children: ReactNode;
}

export default function BackendReadyGate({ children }: Props) {
  const {
    shouldGate,
    status,
    elapsed,
    totalSec,
    errorMessage,
    readyUrl,
    retry,
  } = useBackendReadyPolling();

  useEffect(() => {
    if (shouldGate && status === "ready" && readyUrl) {
      window.location.replace(readyUrl);
    }
  }, [readyUrl, shouldGate, status]);

  // Browser mode, or Tauri after it has navigated to the backend-hosted console.
  if (!shouldGate) {
    return <>{children}</>;
  }

  return (
    <BackendLoadingPage
      status={status}
      elapsed={elapsed}
      totalSec={totalSec}
      errorMessage={errorMessage}
      onRetry={retry}
    />
  );
}
