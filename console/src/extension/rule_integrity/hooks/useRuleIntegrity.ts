import { useState, useEffect, useCallback, useRef } from "react";
import { ruleIntegrityApi } from "../api/client";
import type { ToolGuardRulesIntegrity } from "../api/client";
import { useRuleIntegrityWatch } from "./useRuleIntegrityWatch";

const DEFAULT_FALLBACK_POLL_MS = 60_000;
const SSE_STALE_MS = 90_000;

export function useRuleIntegrity(options?: {
  pollIntervalMs?: number;
  enableWatch?: boolean;
}) {
  const pollIntervalMs = options?.pollIntervalMs ?? DEFAULT_FALLBACK_POLL_MS;
  const enableWatch = options?.enableWatch ?? true;
  const [rulesIntegrity, setRulesIntegrity] =
    useState<ToolGuardRulesIntegrity | null>(null);
  const lastSseAtRef = useRef(0);

  const fetchRulesIntegrity = useCallback(async () => {
    try {
      setRulesIntegrity(await ruleIntegrityApi.getToolGuardRulesIntegrity());
    } catch (integrityErr) {
      console.warn(
        "Failed to load tool guard rule integrity status:",
        integrityErr,
      );
    }
  }, []);

  useEffect(() => {
    void fetchRulesIntegrity();
  }, [fetchRulesIntegrity]);

  useRuleIntegrityWatch(
    (event) => {
      if (event.type !== "rule_integrity_status") {
        return;
      }
      lastSseAtRef.current = Date.now();
      setRulesIntegrity(event);
    },
    enableWatch,
  );

  useEffect(() => {
    if (pollIntervalMs <= 0) {
      return undefined;
    }
    const timer = window.setInterval(() => {
      const sseIsFresh =
        enableWatch &&
        lastSseAtRef.current > 0 &&
        Date.now() - lastSseAtRef.current < SSE_STALE_MS;
      if (sseIsFresh) {
        return;
      }
      void fetchRulesIntegrity();
    }, pollIntervalMs);
    return () => window.clearInterval(timer);
  }, [enableWatch, fetchRulesIntegrity, pollIntervalMs]);

  return {
    rulesIntegrity,
    fetchRulesIntegrity,
  };
}
