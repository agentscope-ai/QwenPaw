import { useState, useEffect, useCallback, useContext } from "react";
import api from "../../../api";
import type { ProviderInfo, ActiveModelsInfo } from "../../../api/types";
import { useAgentStore } from "../../../stores/agentStore";

import { HubModeContext } from "../../../contexts/HubModeContext";
import {
  governanceRequest,
  type MemberModelCatalog,
} from "../../../api/modules/hubGovernance";

export function useProviders() {
  const hubMode = useContext(HubModeContext);
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [activeModels, setActiveModels] = useState<ActiveModelsInfo | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { selectedAgent } = useAgentStore();

  const fetchAll = useCallback(
    async (showLoading = true) => {
      if (showLoading) {
        setLoading(true);
      }
      setError(null);
      try {
        const [provData, activeData, hubCatalog] = await Promise.all([
          api.listProviders(),
          api.getActiveModels({ scope: "global" }),
          hubMode
            ? governanceRequest<MemberModelCatalog>("me/models")
            : Promise.resolve(null),
        ]);
        if (!Array.isArray(provData)) {
          throw new Error(
            "Unexpected API response. Is VITE_API_BASE_URL configured correctly?",
          );
        }
        setProviders(
          hubCatalog
            ? provData.map((provider) =>
                provider.id === "hub-managed"
                  ? {
                      ...provider,
                      models: hubCatalog.models.map((model) => ({
                        id: model.id,
                        name: model.name,
                        supports_image: model.supports_image,
                        supports_multimodal: model.supports_image,
                        supports_video: false,
                        generate_kwargs: {},
                        relay_reasoning: true,
                        thinking_enabled: null,
                        thinking_budget: null,
                        reasoning_effort: null,
                        max_input_length: model.input_token_limit,
                        max_input_length_configured: true,
                      })),
                      extra_models: [],
                    }
                  : provider,
              )
            : provData,
        );
        if (activeData) setActiveModels(activeData);
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
    },
    [hubMode],
  );

  // Re-fetch when agent changes to ensure UI stays in sync even though
  // this page uses scope:"global". If future requirements add agent-scoped
  // models, this dependency will be needed.
  useEffect(() => {
    fetchAll();
  }, [fetchAll, selectedAgent]);

  useEffect(() => {
    if (!providers.some((provider) => provider.models_syncing)) return;

    const timer = window.setInterval(() => {
      void fetchAll(false);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [fetchAll, providers]);

  return {
    providers,
    activeModels,
    loading,
    error,
    fetchAll,
  };
}
