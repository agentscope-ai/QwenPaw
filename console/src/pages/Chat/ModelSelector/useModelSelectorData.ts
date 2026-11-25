import type { SessionModelScope } from "../../../features/session-settings/sessionModel";
import { useCallback, useEffect, useRef, useState } from "react";

import type { ActiveModelsInfo } from "../../../api/types";
import { modelSelectorApi } from "./modelSelectorApi";
import { providerApi } from "../../../api/modules/provider";
import {
  useProviderCatalog,
  type ProviderCatalog,
} from "./useEligibleProviders";

interface UseModelSelectorDataOptions {
  providerCatalog?: ProviderCatalog;
  agentId: string;
  session?: SessionModelScope;
  onActiveModels: (activeModels: ActiveModelsInfo) => void;
}

export function useModelSelectorData({
  agentId,
  session,
  onActiveModels,
  providerCatalog,
}: UseModelSelectorDataOptions) {
  const localCatalog = useProviderCatalog(false);
  const catalog = providerCatalog ?? localCatalog;
  const hasSharedCatalog = providerCatalog !== undefined;
  const { load: loadProviders, setProviders } = catalog;
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

  const updateActiveModels = useCallback((value: ActiveModelsInfo) => {
    activeRequestRef.current += 1;
    setActiveModels(value);
  }, []);

  const fetchData = useCallback(
    async (refresh = true) => {
      const providersRequestId = ++providersRequestRef.current;
      const activeRequestId = ++activeRequestRef.current;
      setLoading(true);
      setLoadError(false);
      try {
        const result = await modelSelectorApi.loadModelSelectorData(
          agentId,
          {
            listProviders: () => loadProviders(refresh),
            getActiveModels: providerApi.getActiveModels,
          },
          session,
          () => {
            if (providersRequestId !== providersRequestRef.current) return;
            setLoading(false);
          },
          (value) => {
            if (activeRequestId !== activeRequestRef.current) return;
            applyActiveModels(value);
          },
        );
        if (providersRequestId !== providersRequestRef.current) return;
        setLoadError(result.loadError);
        return result;
      } finally {
        if (providersRequestId === providersRequestRef.current) {
          setLoading(false);
        }
      }
    },
    [
      agentId,
      session?.sessionId,
      session?.chatId,
      applyActiveModels,
      loadProviders,
    ],
  );

  const refreshActiveModels = useCallback(async () => {
    const requestId = ++activeRequestRef.current;
    const value = await modelSelectorApi.loadActiveModels(agentId, session);
    if (requestId === activeRequestRef.current) applyActiveModels(value);
  }, [agentId, session?.sessionId, session?.chatId, applyActiveModels]);

  useEffect(() => {
    setActiveModels(null);
    void fetchData(!hasSharedCatalog);
    return () => {
      providersRequestRef.current += 1;
      activeRequestRef.current += 1;
    };
  }, [fetchData, hasSharedCatalog]);

  return {
    activeModels,
    fetchData,
    loading,
    loadError,
    providers: catalog.providers ?? [],
    refreshActiveModels,
    setActiveModels: updateActiveModels,
    setProviders,
  };
}
