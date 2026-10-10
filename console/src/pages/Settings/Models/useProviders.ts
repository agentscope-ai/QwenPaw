import { useState, useEffect, useCallback } from "react";
import api from "../../../api";
import type { ProviderInfo, ActiveModelsInfo } from "../../../api/types";
import { useAgentStore } from "../../../stores/agentStore";

export function useProviders() {
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [activeModels, setActiveModels] = useState<ActiveModelsInfo | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const { selectedAgent } = useAgentStore();

  const fetchAll = useCallback(async (showLoading = true) => {
    if (showLoading) {
      setLoading(true);
    }
    setError(null);
    setWarning(null);
    try {
      const [providerResult, activeResult] = await Promise.allSettled([
        api.listProviders(),
        api.getActiveModels({ scope: "global" }),
      ]);
      if (providerResult.status === "rejected") throw providerResult.reason;
      const provData = providerResult.value;
      if (!Array.isArray(provData)) {
        throw new Error(
          "Unexpected API response. Is VITE_API_BASE_URL configured correctly?",
        );
      }
      setProviders(provData);
      setActiveModels(
        activeResult.status === "fulfilled" ? activeResult.value : null,
      );
      const hubError = provData.find(
        (provider) => provider.id === "hub-managed",
      )?.models_last_sync_error;
      setWarning(
        hubError ||
          (activeResult.status === "rejected"
            ? activeResult.reason instanceof Error
              ? activeResult.reason.message
              : "Failed to load active model"
            : null),
      );
    } catch (err) {
      const msg =
        err instanceof Error ? err.message : "Failed to load provider data";
      console.error("Failed to load providers:", err);
      setError(msg);
    } finally {
      if (showLoading) {
        setLoading(false);
      }
    }
  }, []);

  // Re-fetch when agent changes to ensure UI stays in sync even though
  // this page uses scope:"global". If future requirements add agent-scoped
  // models, this dependency will be needed.
  useEffect(() => {
    fetchAll();
  }, [fetchAll, selectedAgent]);

  useEffect(() => {
    if (!providers.some((provider) => provider.models_syncing)) return;

    const timer = window.setInterval(() => {
      void fetchAll(false);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [fetchAll, providers]);

  return {
    providers,
    activeModels,
    loading,
    error,
    warning,
    fetchAll,
  };
}
