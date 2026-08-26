import { useCallback, useEffect, useRef, useState } from "react";

import type { ActiveModelsInfo, ProviderInfo } from "../../../api/types";
import { modelSelectorApi } from "./modelSelectorApi";

interface UseModelSelectorDataOptions {
  agentId: string;
  onActiveModels: (activeModels: ActiveModelsInfo) => void;
}

export function useModelSelectorData({
  agentId,
  onActiveModels,
}: UseModelSelectorDataOptions) {
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [activeModels, setActiveModels] = useState<ActiveModelsInfo | null>(
    null,
  );
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const providersRequestRef = useRef(0);
  const activeRequestRef = useRef(0);

  const applyActiveModels = useCallback(
    (value: ActiveModelsInfo) => {
      setActiveModels(value);
      onActiveModels(value);
    },
    [onActiveModels],
  );

  const fetchData = useCallback(
    async (showLoading = true) => {
      const providersRequestId = ++providersRequestRef.current;
      const activeRequestId = ++activeRequestRef.current;
      if (showLoading) setLoading(true);
      setLoadError(false);
      try {
        const result = await modelSelectorApi.loadModelSelectorData(agentId);
        if (providersRequestId !== providersRequestRef.current) return;
        if (result.providers) setProviders(result.providers);
        if (
          result.activeModels &&
          activeRequestId === activeRequestRef.current
        ) {
          applyActiveModels(result.activeModels);
        }
        setLoadError(result.loadError);
        return result;
      } finally {
        if (showLoading && providersRequestId === providersRequestRef.current) {
          setLoading(false);
        }
      }
    },
    [agentId, applyActiveModels],
  );

  const refreshActiveModels = useCallback(async () => {
    const requestId = ++activeRequestRef.current;
    const value = await modelSelectorApi.loadActiveModels(agentId);
    if (requestId === activeRequestRef.current) applyActiveModels(value);
  }, [agentId, applyActiveModels]);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  useEffect(() => {
    if (!providers.some((provider) => provider.models_syncing)) return;

    const timer = window.setInterval(() => {
      void fetchData(false);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [fetchData, providers]);

  return {
    activeModels,
    fetchData,
    loading,
    loadError,
    providers,
    refreshActiveModels,
    setActiveModels,
    setProviders,
  };
}
