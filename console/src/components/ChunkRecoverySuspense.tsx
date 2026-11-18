import { Suspense, useLayoutEffect } from "react";
import type { ReactNode, SuspenseProps } from "react";
import {
  blockChunkRecoveryHealth,
  markChunkPageHealthy,
} from "../utils/chunkRecovery";

function RecoveryHealth({
  healthy,
  children,
}: {
  healthy: boolean;
  children: ReactNode;
}) {
  // Layout effects also stop when React hides already committed content.
  useLayoutEffect(
    () => (healthy ? markChunkPageHealthy() : blockChunkRecoveryHealth()),
    [healthy],
  );
  return <>{children}</>;
}

/** Count healthy time only while real content is committed and visible. */
export function ChunkRecoverySuspense({ children, fallback }: SuspenseProps) {
  return (
    <Suspense
      fallback={<RecoveryHealth healthy={false}>{fallback}</RecoveryHealth>}
    >
      <RecoveryHealth healthy>{children}</RecoveryHealth>
    </Suspense>
  );
}
