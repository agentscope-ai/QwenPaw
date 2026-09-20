import type { SessionModelScope } from "../../../features/session-settings/sessionModel";
import { useCallback, useEffect, useRef, useState } from "react";

import type { ActiveModelsInfo, ProviderInfo } from "../../../api/types";
import { modelSelectorApi } from "./modelSelectorApi";

interface UseModelSelectorDataOptions {
  agentId: string;
  session?: SessionModelScope;
  onActiveModels: (activeModels: ActiveModelsInfo) => void;
}

export function useModelSelectorData({
  agentId,
  session,
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

  const fetchData = useCallback(async () => {
    const providersRequestId = ++providersRequestRef.current;
    const activeRequestId = ++activeRequestRef.current;
    setLoading(true);
    setLoadError(false);
    try {
      const result = await modelSelectorApi.loadModelSelectorData(
        agentId,
        undefined,
        session,
      );
      if (providersRequestId !== providersRequestRef.current) return;
      if (result.providers) setProviders(result.providers);
      if (result.activeModels && activeRequestId === activeRequestRef.current) {
        applyActiveModels(result.activeModels);
      }
      setLoadError(result.loadError);
      return result;
    } finally {
      if (providersRequestId === providersRequestRef.current) {
        setLoading(false);
      }
    }
  }, [agentId, session?.sessionId, session?.chatId, applyActiveModels]);

  const refreshActiveModels = useCallback(async () => {
    const requestId = ++activeRequestRef.current;
    const value = await modelSelectorApi.loadActiveModels(agentId, session);
    if (requestId === activeRequestRef.current) applyActiveModels(value);
  }, [agentId, session?.sessionId, session?.chatId, applyActiveModels]);

  useEffect(() => {
    setActiveModels(null);
    void fetchData();
    return () => {
      providersRequestRef.current += 1;
      activeRequestRef.current += 1;
    };
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
