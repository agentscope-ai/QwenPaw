import { useState, useEffect, useCallback } from "react";
import api from "../../../api";
import type { ProviderInfo, ActiveModelsInfo } from "../../../api/types";

function normalizeProvidersPayload(payload: unknown): ProviderInfo[] | null {
  if (Array.isArray(payload)) {
    return payload as ProviderInfo[];
  }
  if (payload && typeof payload === "object") {
    const data = payload as { providers?: unknown; data?: unknown };
    if (Array.isArray(data.providers)) {
      return data.providers as ProviderInfo[];
    }
    if (Array.isArray(data.data)) {
      return data.data as ProviderInfo[];
    }
  }
  if (typeof payload === "string") {
    try {
      const parsed = JSON.parse(payload);
      return normalizeProvidersPayload(parsed);
    } catch {
      return null;
    }
  }
  return null;
}

export function useProviders() {
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [activeModels, setActiveModels] = useState<ActiveModelsInfo | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      let provData: unknown;
      let lastProviderErr: unknown = null;

      // Startup on desktop can race with backend init; retry providers briefly.
      for (let i = 0; i < 5; i += 1) {
        try {
          provData = await api.listProviders();
          lastProviderErr = null;
          break;
        } catch (err) {
          lastProviderErr = err;
          await new Promise((resolve) => setTimeout(resolve, 600));
        }
      }
      if (lastProviderErr || provData === undefined) {
        throw lastProviderErr instanceof Error
          ? lastProviderErr
          : new Error("Failed to load provider data");
      }

      const normalizedProviders = normalizeProvidersPayload(provData);
      if (!normalizedProviders) {
        console.error("Unexpected /api/models payload:", provData);
        throw new Error(
          "Unexpected API response. Is BASE_URL configured correctly?",
        );
      }
      setProviders(normalizedProviders);

      // Active model is secondary metadata; do not fail the whole page on error.
      try {
        const activeData = await api.getActiveModels();
        if (activeData) setActiveModels(activeData);
      } catch (err) {
        console.warn("Failed to load active model, keeping providers view:", err);
      }
    } catch (err) {
      const msg =
        err instanceof Error ? err.message : "Failed to load provider data";
      console.error("Failed to load providers:", err);
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAll();
  }, []);  // Empty deps: run once on mount

  return {
    providers,
    activeModels,
    loading,
    error,
    fetchAll,
  };
}
