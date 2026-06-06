import { useCallback, useEffect, useState } from "react";
import { providerApi } from "../../../api/modules/provider";
import type { ProviderInfo, ModelInfo } from "../../../api/types";

export interface MultimodalCaps {
  supportsMultimodal: boolean;
  supportsImage: boolean;
  supportsVideo: boolean;
}

const NO_CAPS: MultimodalCaps = {
  supportsMultimodal: false,
  supportsImage: false,
  supportsVideo: false,
};

export function useMultimodalCapabilities(
  selectedAgent: string,
): MultimodalCaps {
  const [caps, setCaps] = useState<MultimodalCaps>(NO_CAPS);

  const fetchCaps = useCallback(async () => {
    try {
      const [providers, activeModels] = await Promise.all([
        providerApi.listProviders(),
        providerApi.getActiveModels({
          scope: "effective",
          agent_id: selectedAgent,
        }),
      ]);
      const providerId = activeModels?.active_llm?.provider_id;
      const modelId = activeModels?.active_llm?.model;
      if (!providerId || !modelId) {
        setCaps(NO_CAPS);
        return;
      }

      const provider = (providers as ProviderInfo[]).find(
        (p) => p.id === providerId,
      );
      if (!provider) {
        setCaps(NO_CAPS);
        return;
      }

      const allModels: ModelInfo[] = [
        ...(provider.models ?? []),
        ...(provider.extra_models ?? []),
      ];
      const model = allModels.find((m) => m.id === modelId);
      setCaps({
        supportsMultimodal: model?.supports_multimodal ?? false,
        supportsImage: model?.supports_image ?? false,
        supportsVideo: model?.supports_video ?? false,
      });
    } catch {
      setCaps(NO_CAPS);
    }
  }, [selectedAgent]);

  useEffect(() => {
    fetchCaps();
  }, [fetchCaps]);

  useEffect(() => {
    const handler = () => {
      fetchCaps();
    };
    window.addEventListener("model-switched", handler);
    return () => window.removeEventListener("model-switched", handler);
  }, [fetchCaps]);

  return caps;
}
