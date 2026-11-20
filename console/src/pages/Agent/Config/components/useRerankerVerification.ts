import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { RerankerHistoryRecord } from "@/api/modules/agent";
import type { RerankerConfig } from "@/api/types/agent";
import { useAgentStore } from "@/stores/agentStore";
import { useRerankerVerificationStore } from "@/stores/rerankerVerificationStore";
import { getRerankerConfigKey } from "./rerankerUtils";

const EMPTY_HISTORY: RerankerHistoryRecord[] = [];

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
  const history = useRerankerVerificationStore(
    (state) => state.historyByAgent[agentId] ?? EMPTY_HISTORY,
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

  // Synchronous in-memory identity. No WebCrypto: `crypto.subtle` is missing
  // on a plain-HTTP console served from a non-loopback origin, and history
  // lookup is done server-side from the saved agent config.
  const configKey = useMemo(
    () => getRerankerConfigKey(config),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [config?.base_url, config?.api_key, config?.model_name, config?.timeout],
  );

  // Latest values for stale-response checks (callbacks close over old renders).
  const configKeyRef = useRef(configKey);
  useEffect(() => {
    configKeyRef.current = configKey;
  }, [configKey]);
  const agentIdRef = useRef(agentId);
  useEffect(() => {
    agentIdRef.current = agentId;
  }, [agentId]);

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
      testedConfigKey?: string,
    ) => {
      const key = testedConfigKey || configKey;
      // A verdict for a service the form has since moved away from must not
      // be presented as the current one.
      const live = configKeyRef.current;
      if (live && key !== live) return;
      setVerification(agentId, {
        configKey: key,
        latency,
        precision,
        correctCount,
        total,
        verifiedAt: Date.now(),
      });
    },
    [agentId, configKey, setVerification],
  );

  /**
   * Refresh the stored history series. History is a separate slice, so it can
   * neither manufacture nor replace a successful verification verdict.
   *
   * A read that started before a newer run was recorded can resolve
   * afterwards; keep the newer series instead of regressing it.
   */
  const setHistory = useCallback(
    (records: RerankerHistoryRecord[]) => {
      const existing =
        useRerankerVerificationStore.getState().historyByAgent[agentId] ?? [];
      const existingLast =
        existing[existing.length - 1]?.ts ?? Number.NEGATIVE_INFINITY;
      const incomingLast =
        records[records.length - 1]?.ts ?? Number.NEGATIVE_INFINITY;
      if (incomingLast < existingLast) return;
      setStoredHistory(agentId, records);
    },
    [agentId, setStoredHistory],
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
    Boolean(configKey) && verifiedReranker?.configKey === configKey;

  return {
    agentId,
    testingReranker,
    setTestingReranker,
    testedReranker: verifiedReranker,
    testedRerankerIsCurrent,
    history,
    configKey,
    markVerified,
    setHistory,
    clearVerification,
  };
}