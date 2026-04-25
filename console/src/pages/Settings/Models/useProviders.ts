import { useState, useEffect, useCallback } from "react";
import api from "../../../api";
import type {
  ProviderInfo,
  ActiveModelsInfo,
  RoutingConfig,
} from "../../../api/types";

export function useProviders() {
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [activeModels, setActiveModels] = useState<ActiveModelsInfo | null>(
    null,
  );
  const [routingConfig, setRoutingConfig] = useState<RoutingConfig | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchAll = useCallback(async (showLoading = true) => {
    if (showLoading) {
      setLoading(true);
    }
    setError(null);
    try {
      const [provData, activeData, routingData] = await Promise.all([
        api.listProviders(),
        api.getActiveModels({ scope: "global" }),
        api.getRoutingConfig(),
      ]);
      if (!Array.isArray(provData)) {
        throw new Error(
          "Unexpected API response. Is VITE_API_BASE_URL configured correctly?",
        );
      }
      setProviders(provData);
      if (activeData) setActiveModels(activeData);
      if (routingData) setRoutingConfig(routingData);
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

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  return {
    providers,
    activeModels,
    routingConfig,
    loading,
    error,
    fetchAll,
  };
}
