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
  const verifiedReranker = useRerankerVerificationStore(
    (state) => state.verificationByAgent[agentId] ?? null,
  );
  const storedHistory = useRerankerVerificationStore(
    (state) => state.historyByAgent[agentId] ?? null,
  );
  const setVerification = useRerankerVerificationStore(
    (state) => state.setVerification,
  );
  const setStoredHistory = useRerankerVerificationStore(
    (state) => state.setHistory,
  );
  const clearStoredVerification = useRerankerVerificationStore(
    (state) => state.clearVerification,
  );
  const previousAgentIdRef = useRef(agentId);

  // The fingerprint is async (SHA-256 via WebCrypto). Compute it once here and
  // expose the resolved value so the component does not duplicate the
  // computation, and so history loading and manual verification always compare
  // against the same value.
  const fingerprintPromise = useMemo(
    () => getRerankerServiceFingerprint(config),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [config?.base_url, config?.api_key, config?.model_name, config?.timeout],
  );
  const [serviceFingerprint, setServiceFingerprint] = useState("");
  useEffect(() => {
    let cancelled = false;
    fingerprintPromise
      .then((fingerprint) => {
        if (!cancelled) setServiceFingerprint(fingerprint);
      })
      .catch(() => {
        if (!cancelled) setServiceFingerprint("");
      });
    return () => {
      cancelled = true;
    };
  }, [fingerprintPromise]);

  // Live fingerprint for stale-response checks (state updates lag the
  // promise resolution by one render).
  const serviceFingerprintRef = useRef("");
  useEffect(() => {
    serviceFingerprintRef.current = serviceFingerprint;
  }, [serviceFingerprint]);

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
      testedFingerprint?: string,
    ) => {
      const fingerprint = testedFingerprint || (await fingerprintPromise);
      // A verdict for a service the form has since moved away from must not
      // be presented as the current one.
      const live = serviceFingerprintRef.current;
      if (live && fingerprint !== live) return;
      setVerification(agentId, {
        fingerprint,
        latency,
        precision,
        correctCount,
        total,
        verifiedAt: Date.now(),
      });
    },
    [agentId, fingerprintPromise, setVerification],
  );

  /**
   * Refresh the stored history series. History is a separate slice, so it can
   * neither manufacture nor replace a successful verification verdict.
   *
   * `requestedFingerprint` is captured when the fetch starts; if the live
   * fingerprint has moved on, the response belongs to a superseded service and
   * is dropped instead of clobbering the current state.
   */
  const setHistory = useCallback(
    async (
      history: RerankerHistoryRecord[],
      requestedFingerprint?: string,
    ) => {
      const fingerprint = requestedFingerprint ?? (await fingerprintPromise);
      if (!fingerprint) return;
      const live = serviceFingerprintRef.current;
      if (live && fingerprint !== live) return;
      if (fingerprint !== (await fingerprintPromise)) return;
      // A history read that started before a newer run was recorded can
      // resolve afterwards. Keep the newer series instead of regressing it.
      const existing =
        useRerankerVerificationStore.getState().historyByAgent[agentId];
      if (existing && existing.fingerprint === fingerprint) {
        const existingLast =
          existing.records[existing.records.length - 1]?.ts ??
          Number.NEGATIVE_INFINITY;
        const incomingLast =
          history[history.length - 1]?.ts ?? Number.NEGATIVE_INFINITY;
        if (incomingLast < existingLast) return;
      }
      setStoredHistory(agentId, { fingerprint, records: history });
    },
    [agentId, fingerprintPromise, setStoredHistory],
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
    Boolean(serviceFingerprint) &&
    verifiedReranker?.fingerprint === serviceFingerprint;
  const historyIsCurrent =
    Boolean(serviceFingerprint) &&
    storedHistory?.fingerprint === serviceFingerprint;
  const history = historyIsCurrent ? storedHistory.records : [];

  return {
    testingReranker,
    setTestingReranker,
    testedReranker: verifiedReranker,
    testedRerankerIsCurrent,
    history,
    serviceFingerprint,
    markVerified,
    setHistory,
    clearVerification,
  };
}