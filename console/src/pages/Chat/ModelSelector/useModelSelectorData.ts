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
  const fetchRequestRef = useRef(0);
  const providersRequestRef = useRef(0);
  const activeRequestRef = useRef(0);

  const applyActiveModels = useCallback(
    (value: ActiveModelsInfo) => {
      setActiveModelsState(value);
      onActiveModels(value);
    },
    [onActiveModels],
  );

  const fetchData = useCallback(async () => {
    const fetchRequestId = ++fetchRequestRef.current;
    const providersRequestId = ++providersRequestRef.current;
    const activeRequestId = ++activeRequestRef.current;
    setLoading(true);
    setLoadError(false);
    try {
      const result = await modelSelectorApi.loadModelSelectorData(agentId);
      if (
        result.providers &&
        providersRequestId === providersRequestRef.current
      ) {
        setProviders(result.providers);
      }
      if (result.activeModels && activeRequestId === activeRequestRef.current) {
        applyActiveModels(result.activeModels);
      }
      if (fetchRequestId !== fetchRequestRef.current) return;
      setLoadError(result.loadError);
      return result;
    } finally {
      if (fetchRequestId === fetchRequestRef.current) {
        setLoading(false);
      }
    }
  }, [agentId, applyActiveModels]);

  const refreshProviders = useCallback(async () => {
    const requestId = ++providersRequestRef.current;
    try {
      const value = await modelSelectorApi.loadProviders();
      if (requestId === providersRequestRef.current) setProviders(value);
    } catch {
      return;
    }
  }, []);

  const commitActiveModels = useCallback((value: ActiveModelsInfo) => {
    activeRequestRef.current += 1;
    setActiveModelsState(value);
  }, []);

  const refreshActiveModels = useCallback(async () => {
    const requestId = ++activeRequestRef.current;
    const value = await modelSelectorApi.loadActiveModels(agentId);
    if (requestId === activeRequestRef.current) applyActiveModels(value);
  }, [agentId, applyActiveModels]);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  const modelsSyncing = providers.some((provider) => provider.models_syncing);

  useEffect(() => {
    if (!modelsSyncing) return;

    let cancelled = false;
    let timer: number | undefined;
    const schedule = () => {
      timer = window.setTimeout(() => {
        void refreshProviders().finally(() => {
          if (!cancelled) schedule();
        });
      }, 1000);
    };
    schedule();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [modelsSyncing, refreshProviders]);

  return {
    activeModels,
    commitActiveModels,
    fetchData,
    loading,
    loadError,
    providers,
    refreshActiveModels,
    setProviders,
  };
}
