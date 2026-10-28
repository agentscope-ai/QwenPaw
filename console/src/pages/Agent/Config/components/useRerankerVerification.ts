import { useCallback, useEffect, useRef, useState } from "react";

import type { RerankerConfig } from "@/api/types/agent";
import { useAgentStore } from "@/stores/agentStore";
import { useRerankerVerificationStore } from "@/stores/rerankerVerificationStore";
import { getRerankerServiceFingerprint } from "./rerankerUtils";

export function useRerankerVerification(
  config: RerankerConfig | undefined,
  configured: boolean,
) {
  const { selectedAgent } = useAgentStore();
  const agentId = selectedAgent || "default";
  const [testingReranker, setTestingReranker] = useState(false);
  const testedReranker = useRerankerVerificationStore(
    (state) => state.verificationByAgent[agentId] ?? null,
  );
  const setVerification = useRerankerVerificationStore(
    (state) => state.setVerification,
  );
  const clearStoredVerification = useRerankerVerificationStore(
    (state) => state.clearVerification,
  );
  const previousAgentIdRef = useRef(agentId);

  const clearVerification = useCallback(
    () => clearStoredVerification(agentId),
    [agentId, clearStoredVerification],
  );
  const markVerified = useCallback(
    (
      latency: number,
      rankingCorrect: boolean | null,
      scores: number[] | null,
    ) => {
      setVerification(agentId, {
        fingerprint: getRerankerServiceFingerprint(config),
        latency,
        scores,
        rankingCorrect,
        verifiedAt: Date.now(),
      });
    },
    [agentId, config, setVerification],
  );

  useEffect(() => {
    const agentChanged = previousAgentIdRef.current !== agentId;
    previousAgentIdRef.current = agentId;

    // The selected agent updates before the shared form is repopulated. On
    // that transition frame, `config` still belongs to the previous agent and
    // must not clear the newly selected agent's stored verification.
    if (!agentChanged && config !== undefined && !configured)
      clearVerification();
  }, [agentId, clearVerification, config, configured]);

  const testedRerankerIsCurrent =
    testedReranker?.fingerprint === getRerankerServiceFingerprint(config);

  return {
    testingReranker,
    setTestingReranker,
    testedReranker,
    testedRerankerIsCurrent,
    markVerified,
    clearVerification,
  };
}
