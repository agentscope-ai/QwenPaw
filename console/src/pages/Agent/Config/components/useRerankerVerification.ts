import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "@/api";
import type {
  RerankerHistoryRecord,
  RerankerTestResponse,
} from "@/api/modules/agent";
import type { RerankerConfig } from "@/api/types/agent";
import { useAgentStore } from "@/stores/agentStore";
import { useRerankerVerificationStore } from "@/stores/rerankerVerificationStore";
import { getRerankerConfigKey, isRerankerConfigured } from "./rerankerUtils";

const EMPTY_HISTORY: RerankerHistoryRecord[] = [];

export type RerankerProbeOutcome =
  | { status: "stale" }
  | { status: "success"; result: RerankerTestResponse }
  | { status: "failed"; message: string };

export function useRerankerVerification(
  config: RerankerConfig | undefined,
  configured: boolean,
) {
  const { selectedAgent } = useAgentStore();
  const agentId = selectedAgent || "default";
  const [testingReranker, setTestingReranker] = useState(false);

  // Synchronous in-memory identity. No WebCrypto: `crypto.subtle` is missing
  // on a plain-HTTP console served from a non-loopback origin, and history
  // lookup is done server-side from the saved agent config.
  const configKey = useMemo(
    () => getRerankerConfigKey(config),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [config?.base_url, config?.api_key, config?.model_name, config?.timeout],
  );

  const verifiedReranker = useRerankerVerificationStore(
    (state) => state.verificationByAgent[agentId] ?? null,
  );
  const history = useRerankerVerificationStore((state) => {
    if (!configured || !configKey) return EMPTY_HISTORY;
    return state.historyByAgent[agentId]?.[configKey]?.records ?? EMPTY_HISTORY;
  });
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

  // Latest values & lifecycle tokens for stale-response checks (async
  // callbacks close over old renders and may resolve after unmount).
  const mountedRef = useRef(true);
  const requestIdRef = useRef(0);
  const historyLoadIdRef = useRef(0);
  const configKeyRef = useRef(configKey);
  const configuredRef = useRef(configured);
  const agentIdRef = useRef(agentId);

  useEffect(() => {
    configKeyRef.current = configKey;
  }, [configKey]);
  useEffect(() => {
    configuredRef.current = configured;
  }, [configured]);
  useEffect(() => {
    agentIdRef.current = agentId;
    historyLoadIdRef.current += 1;
  }, [agentId]);
  useEffect(() => {
    // Switching agent, changing service fields, or disabling reranking
    // immediately abandons any in-flight manual probe and unlocks the button
    // for the new service.
    requestIdRef.current += 1;
    setTestingReranker(false);
  }, [agentId, configKey, configured]);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      requestIdRef.current += 1;
      historyLoadIdRef.current += 1;
    };
  }, []);

  const isMounted = useCallback(() => mountedRef.current, []);

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
   * Refresh the stored history series for the active (or specified) service.
   * History is a separate slice scoped by service key, so it can neither
   * manufacture a verdict nor leak across models within the same agent.
   */
  const setHistory = useCallback(
    (
      records: RerankerHistoryRecord[],
      fingerprint = "",
      targetConfigKey?: string,
    ) => {
      const key = targetConfigKey || configKeyRef.current;
      if (!key) return;
      setStoredHistory(agentId, key, records, fingerprint);
    },
    [agentId, setStoredHistory],
  );

  /**
   * Load persisted history for the agent's saved reranker configuration.
   *
   * Associates the returned fingerprint with the service key that was active
   * when the load started (or an existing entry already carrying that
   * fingerprint), so editing the model in the form never shows another
   * service's history.
   */
  const loadHistory = useCallback(
    async (requestedConfigKey?: string) => {
      const targetKey = requestedConfigKey || configKeyRef.current;
      if (!targetKey) return;
      const requestedAgentId = agentIdRef.current;
      const loadId = ++historyLoadIdRef.current;
      try {
        const res = await api.getRerankerHistory();
        if (
          !mountedRef.current ||
          loadId !== historyLoadIdRef.current ||
          agentIdRef.current !== requestedAgentId
        ) {
          return;
        }
        if (!res.fingerprint) return;
        const agentHistory =
          useRerankerVerificationStore.getState().historyByAgent[
            requestedAgentId
          ] ?? {};
        const matchedByFingerprint = Object.values(agentHistory).find(
          (entry) => entry.fingerprint === res.fingerprint,
        );
        const scopedKey = matchedByFingerprint?.configKey ?? targetKey;
        setStoredHistory(
          requestedAgentId,
          scopedKey,
          res.history,
          res.fingerprint,
        );
      } catch {
        // History is best-effort; a failed fetch must not block the UI.
      }
    },
    [setStoredHistory],
  );

  /**
   * Run a manual probe and update verification/history state while guarding
   * against stale responses, agent/config switches, and component unmount.
   */
  const runManualProbe = useCallback(
    async (
      probeConfig: RerankerConfig,
      getLiveConfig?: () => RerankerConfig | undefined,
    ): Promise<RerankerProbeOutcome> => {
      setTestingReranker(true);
      const requestId = ++requestIdRef.current;
      const testedAgentId = agentIdRef.current;
      const testedConfigKey = getRerankerConfigKey(probeConfig);
      const isCurrent = () => {
        if (
          !mountedRef.current ||
          requestId !== requestIdRef.current ||
          agentIdRef.current !== testedAgentId ||
          configKeyRef.current !== testedConfigKey
        ) {
          return false;
        }
        if (getLiveConfig) {
          return isRerankerConfigured(getLiveConfig());
        }
        return configuredRef.current;
      };

      try {
        const result = await api.testReranker(probeConfig);
        if (!isCurrent()) return { status: "stale" };
        if (result.success) {
          setVerification(testedAgentId, {
            configKey: testedConfigKey,
            latency: result.latency_ms,
            precision: result.precision,
            correctCount: result.correct_count,
            total: result.total,
            verifiedAt: Date.now(),
          });
          // Only refresh history when the server returned a series; if history
          // persistence failed (`result.history === null`), keep any existing
          // displayed trend instead of overwriting it with an empty array.
          if (result.history !== null) {
            setStoredHistory(
              testedAgentId,
              testedConfigKey,
              result.history,
              result.fingerprint ?? "",
            );
          }
          return { status: "success", result };
        }
        // Clear only the verification badge; preserve the historical trend.
        clearStoredVerification(testedAgentId);
        return { status: "failed", message: result.message };
      } catch (error) {
        if (!isCurrent()) return { status: "stale" };
        clearStoredVerification(testedAgentId);
        return {
          status: "failed",
          message: error instanceof Error ? error.message : String(error),
        };
      } finally {
        if (mountedRef.current && requestId === requestIdRef.current) {
          setTestingReranker(false);
        }
      }
    },
    [clearStoredVerification, setStoredHistory, setVerification],
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
    isMounted,
    markVerified,
    setHistory,
    loadHistory,
    runManualProbe,
    clearVerification,
  };
}
