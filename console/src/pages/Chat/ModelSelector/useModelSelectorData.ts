import { useCallback, useEffect, useRef, useState } from "react";

import type { ActiveModelsInfo, ProviderInfo } from "../../../api/types";
import { modelSelectorApi } from "./modelSelectorApi";

interface UseModelSelectorDataOptions {
  agentId: string;
}

export function useModelSelectorData({ agentId }: UseModelSelectorDataOptions) {
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [activeModels, setActiveModels] = useState<ActiveModelsInfo | null>(
    null,
  );
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const providersRequestRef = useRef(0);
  const activeRequestRef = useRef(0);

  const fetchData = useCallback(async () => {
    const providersRequestId = ++providersRequestRef.current;
    const activeRequestId = ++activeRequestRef.current;
    setLoading(true);
    setLoadError(false);
    try {
      const result = await modelSelectorApi.loadModelSelectorData(agentId);
      if (providersRequestId !== providersRequestRef.current) return;
      if (result.providers) setProviders(result.providers);
      if (result.activeModels && activeRequestId === activeRequestRef.current) {
        setActiveModels(result.activeModels);
      }
      setLoadError(result.loadError);
      return result;
    } finally {
      if (providersRequestId === providersRequestRef.current) {
        setLoading(false);
      }
    }
  }, [agentId]);

  const refreshActiveModels = useCallback(async () => {
    const requestId = ++activeRequestRef.current;
    const value = await modelSelectorApi.loadActiveModels(agentId);
    if (requestId === activeRequestRef.current) setActiveModels(value);
  }, [agentId]);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

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
