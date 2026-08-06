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
  const activeRequestRef = useRef(0);

  const applyActiveModels = useCallback(
    (value: ActiveModelsInfo) => {
      setActiveModels(value);
      onActiveModels(value);
    },
    [onActiveModels],
  );

  const fetchData = useCallback(async () => {
    const requestId = ++activeRequestRef.current;
    setLoading(true);
    setLoadError(false);
    try {
      const result = await modelSelectorApi.loadModelSelectorData(agentId);
      if (requestId !== activeRequestRef.current) return;
      if (result.providers) setProviders(result.providers);
      if (result.activeModels) applyActiveModels(result.activeModels);
      setLoadError(result.loadError);
    } finally {
      if (requestId === activeRequestRef.current) setLoading(false);
    }
  }, [agentId, applyActiveModels]);

  const refreshActiveModels = useCallback(async () => {
    const requestId = ++activeRequestRef.current;
    const value = await modelSelectorApi.loadActiveModels(agentId);
    if (requestId === activeRequestRef.current) applyActiveModels(value);
  }, [agentId, applyActiveModels]);

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
