import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { RerankerHistoryRecord } from "@/api/modules/agent";
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

  // The fingerprint is async (SHA-256 via WebCrypto) and must be stable
  // across renders so history loading and manual verification compare
  // against the same value.
  const fingerprintPromise = useMemo(
    () => getRerankerServiceFingerprint(config),
    [config?.base_url, config?.api_key, config?.model_name, config?.timeout],
  );

  const clearVerification = useCallback(
    () => clearStoredVerification(agentId),
    [agentId, clearStoredVerification],
  );

  const markVerified = useCallback(
    async (
      latency: number,
      precision: number | null,
      correctCount: number,
      total: number,
      history: RerankerHistoryRecord[],
    ) => {
      const fingerprint = await fingerprintPromise;
      setVerification(agentId, {
        fingerprint,
        latency,
        precision,
        correctCount,
        total,
        history,
        verifiedAt: Date.now(),
      });
    },
    [agentId, fingerprintPromise, setVerification],
  );

  /**
   * Merge fetched history into the current verification state without ever
   * manufacturing a successful verification: an absent or history-only
   * service keeps verifiedAt=0 and shows the history-only precision slot,
   * and a late history response never erases a completed manual result.
   */
  const setHistory = useCallback(
    async (history: RerankerHistoryRecord[]) => {
      const fingerprint = await fingerprintPromise;
      if (!fingerprint) return;
      const existing = useRerankerVerificationStore.getState()
        .verificationByAgent[agentId];
      if (
        existing &&
        existing.fingerprint === fingerprint &&
        existing.verifiedAt > 0
      ) {
        // A manual verification for this exact service already exists; only
        // refresh its history series.
        setVerification(agentId, { ...existing, history });
        return;
      }
      setVerification(agentId, {
        fingerprint,
        latency: 0,
        precision: null,
        correctCount: 0,
        total: 0,
        history,
        verifiedAt: 0,
      });
    },
    [agentId, fingerprintPromise, setVerification],
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

  const [currentFingerprint, setCurrentFingerprint] = useState("");
  useEffect(() => {
    let cancelled = false;
    fingerprintPromise.then((fingerprint) => {
      if (!cancelled) setCurrentFingerprint(fingerprint);
    });
    return () => {
      cancelled = true;
    };
  }, [fingerprintPromise]);

  const testedRerankerIsCurrent =
    testedReranker?.fingerprint === currentFingerprint;

  return {
    testingReranker,
    setTestingReranker,
    testedReranker,
    testedRerankerIsCurrent,
    markVerified,
    setHistory,
    clearVerification,
  };
}
