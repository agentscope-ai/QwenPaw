import { useState, useEffect, useCallback, useRef } from "react";
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
  const { selectedAgent } = useAgentStore();
  const fetchRequestRef = useRef(0);
  const providersRequestRef = useRef(0);
  const activeRequestRef = useRef(0);

  const fetchAll = useCallback(async (showLoading = true) => {
    const fetchRequestId = ++fetchRequestRef.current;
    const providersRequestId = ++providersRequestRef.current;
    const activeRequestId = ++activeRequestRef.current;
    if (showLoading) {
      setLoading(true);
    }
    setError(null);
    try {
      const [provData, activeData] = await Promise.all([
        api.listProviders(),
        api.getActiveModels({ scope: "global" }),
      ]);
      if (!Array.isArray(provData)) {
        throw new Error(
          "Unexpected API response. Is VITE_API_BASE_URL configured correctly?",
        );
      }
      if (providersRequestId === providersRequestRef.current) {
        setProviders(provData);
      }
      if (activeData && activeRequestId === activeRequestRef.current) {
        setActiveModels(activeData);
      }
    } catch (err) {
      if (fetchRequestId !== fetchRequestRef.current) return;
      const msg =
        err instanceof Error ? err.message : "Failed to load provider data";
      console.error("Failed to load providers:", err);
      setError(msg);
    } finally {
      if (showLoading && fetchRequestId === fetchRequestRef.current) {
        setLoading(false);
      }
    }
  }, []);

  const refreshProviders = useCallback(async () => {
    const requestId = ++providersRequestRef.current;
    try {
      const provData = await api.listProviders();
      if (!Array.isArray(provData)) return;
      if (requestId === providersRequestRef.current) {
        setProviders(provData);
      }
    } catch {
      return;
    }
  }, []);

  // Re-fetch when agent changes to ensure UI stays in sync even though
  // this page uses scope:"global". If future requirements add agent-scoped
  // models, this dependency will be needed.
  useEffect(() => {
    fetchAll();
  }, [fetchAll, selectedAgent]);

  const modelsSyncing = providers.some(
    (provider) => provider.models_syncing,
  );

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
    providers,
    activeModels,
    loading,
    error,
    fetchAll,
  };
}
