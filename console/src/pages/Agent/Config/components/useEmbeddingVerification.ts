import { useCallback, useEffect, useState } from "react";

import type { EmbeddingModelConfig } from "@/api/types/agent";
import { useAgentStore } from "@/stores/agentStore";
import { useEmbeddingVerificationStore } from "@/stores/embeddingVerificationStore";
import { getEmbeddingServiceFingerprint } from "./embeddingUtils";

export function useEmbeddingVerification(
  config: EmbeddingModelConfig | undefined,
  enabled: boolean,
) {
  const { selectedAgent } = useAgentStore();
  const agentId = selectedAgent || "default";
  const [testingEmbedding, setTestingEmbedding] = useState(false);
  const testedEmbedding = useEmbeddingVerificationStore(
    (state) => state.verificationByAgent[agentId] ?? null,
  );
  const setVerification = useEmbeddingVerificationStore(
    (state) => state.setVerification,
  );
  const clearStoredVerification = useEmbeddingVerificationStore(
    (state) => state.clearVerification,
  );

  const clearVerification = useCallback(
    () => clearStoredVerification(agentId),
    [agentId, clearStoredVerification],
  );
  const markVerified = useCallback(
    (dimensions: number, latency: number) => {
      setVerification(agentId, {
        fingerprint: getEmbeddingServiceFingerprint(config),
        dimensions,
        latency,
        verifiedAt: Date.now(),
      });
    },
    [agentId, config, setVerification],
  );

  useEffect(() => {
    if (config !== undefined && !enabled) clearVerification();
  }, [clearVerification, config, enabled]);

  const testedEmbeddingIsCurrent =
    testedEmbedding?.fingerprint === getEmbeddingServiceFingerprint(config);

  return {
    testingEmbedding,
    setTestingEmbedding,
    testedEmbedding,
    testedEmbeddingIsCurrent,
    markVerified,
    clearVerification,
  };
}
