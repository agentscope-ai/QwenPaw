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
  const [activeModels, setActiveModelsState] =
    useState<ActiveModelsInfo | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const providersRequestRef = useRef(0);
  const activeRequestRef = useRef(0);
  const lastAppliedActiveRequestRef = useRef(0);
  const activeAgentRef = useRef(agentId);
  const activeRefreshRef = useRef<{
    agentId: string;
    promise: Promise<void>;
  } | null>(null);
  activeAgentRef.current = agentId;

  const applyActiveModels = useCallback(
    (value: ActiveModelsInfo) => {
      setActiveModelsState(value);
      onActiveModels(value);
    },
    [onActiveModels],
  );

  const commitActiveModels = useCallback(
    (value: ActiveModelsInfo) => {
      const requestId = ++activeRequestRef.current;
      lastAppliedActiveRequestRef.current = requestId;
      applyActiveModels(value);
    },
    [applyActiveModels],
  );

  const applyActiveModelsIfNewest = useCallback(
    (requestId: number, requestAgentId: string, value: ActiveModelsInfo) => {
      if (
        requestAgentId !== activeAgentRef.current ||
        requestId <= lastAppliedActiveRequestRef.current
      ) {
        return;
      }
      lastAppliedActiveRequestRef.current = requestId;
      applyActiveModels(value);
    },
    [applyActiveModels],
  );

  const fetchData = useCallback(async () => {
    const providersRequestId = ++providersRequestRef.current;
    const activeRequestId = ++activeRequestRef.current;
    setLoading(true);
    setLoadError(false);
    try {
      const result = await modelSelectorApi.loadModelSelectorData(agentId);
      if (providersRequestId !== providersRequestRef.current) return;
      if (result.providers) setProviders(result.providers);
      if (result.activeModels) {
        applyActiveModelsIfNewest(
          activeRequestId,
          agentId,
          result.activeModels,
        );
      }
      setLoadError(result.loadError);
      return result;
    } finally {
      if (providersRequestId === providersRequestRef.current) {
        setLoading(false);
      }
    }
  }, [agentId, applyActiveModelsIfNewest]);

  const refreshActiveModels = useCallback(() => {
    const inFlight = activeRefreshRef.current;
    if (inFlight?.agentId === agentId) return inFlight.promise;

    const requestId = ++activeRequestRef.current;
    const promise = modelSelectorApi
      .loadActiveModels(agentId)
      .then((value) => {
        applyActiveModelsIfNewest(requestId, agentId, value);
      })
      .finally(() => {
        if (activeRefreshRef.current?.promise === promise) {
          activeRefreshRef.current = null;
        }
      });
    activeRefreshRef.current = { agentId, promise };
    return promise;
  }, [agentId, applyActiveModelsIfNewest]);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  useEffect(() => {
    const refreshWhenVisible = () => {
      if (document.visibilityState === "hidden") return;
      void refreshActiveModels().catch(() => {
        // Keep the last known model when the backend is temporarily offline.
      });
    };

    const handlePageShow = (event: PageTransitionEvent) => {
      if (event.persisted) refreshWhenVisible();
    };

    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") refreshWhenVisible();
    };

    window.addEventListener("online", refreshWhenVisible);
    window.addEventListener("pageshow", handlePageShow);
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      window.removeEventListener("online", refreshWhenVisible);
      window.removeEventListener("pageshow", handlePageShow);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [refreshActiveModels]);

  return {
    activeModels,
    fetchData,
    loading,
    loadError,
    providers,
    refreshActiveModels,
    commitActiveModels,
    setProviders,
  };
}
