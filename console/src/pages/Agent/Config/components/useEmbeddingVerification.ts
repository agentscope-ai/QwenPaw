import { useCallback, useEffect, useState } from "react";

import type { EmbeddingModelConfig } from "@/api/types/agent";
import { useAgentStore } from "@/stores/agentStore";
import { getEmbeddingServiceFingerprint } from "./embeddingUtils";

interface VerifiedEmbedding {
  agentId: string;
  fingerprint: string;
  dimensions: number;
  latency: number;
}

export function useEmbeddingVerification(
  config: EmbeddingModelConfig | undefined,
  enabled: boolean,
  configRevision: number,
) {
  const { selectedAgent } = useAgentStore();
  const agentId = selectedAgent || "default";
  const [testingEmbedding, setTestingEmbedding] = useState(false);
  const [testedEmbedding, setTestedEmbedding] =
    useState<VerifiedEmbedding | null>(null);

  const clearVerification = useCallback(() => setTestedEmbedding(null), []);
  const markVerified = useCallback(
    (dimensions: number, latency: number) => {
      setTestedEmbedding({
        agentId,
        fingerprint: getEmbeddingServiceFingerprint(config),
        dimensions,
        latency,
      });
    },
    [agentId, config],
  );

  useEffect(clearVerification, [agentId, configRevision, clearVerification]);
  useEffect(() => {
    if (!enabled) clearVerification();
  }, [clearVerification, enabled]);

  const testedEmbeddingIsCurrent =
    testedEmbedding?.agentId === agentId &&
    testedEmbedding.fingerprint === getEmbeddingServiceFingerprint(config);

  return {
    testingEmbedding,
    setTestingEmbedding,
    testedEmbedding,
    testedEmbeddingIsCurrent,
    markVerified,
    clearVerification,
  };
}
