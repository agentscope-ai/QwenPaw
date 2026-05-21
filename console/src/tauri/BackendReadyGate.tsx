import { type ReactNode } from "react";
import BackendLoadingPage from "./BackendLoadingPage";
import useBackendReadyPolling from "./useBackendReadyPolling";

interface Props {
  children: ReactNode;
}

export default function BackendReadyGate({ children }: Props) {
  const { shouldGate, status, elapsed, totalSec, errorMessage, retry } =
    useBackendReadyPolling();

  // Browser mode or backend ready.
  if (!shouldGate || status === "ready") {
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
