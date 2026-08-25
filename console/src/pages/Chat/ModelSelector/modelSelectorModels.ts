import type { ProviderInfo } from "../../../api/types";

export interface EligibleProvider {
  id: string;
  name: string;
  models: ProviderInfo["models"];
  is_free_tier?: boolean;
  is_custom?: boolean;
  is_local?: boolean;
  supports_oauth?: boolean;
  oauth_connected?: boolean;
  has_api_key?: boolean;
  require_api_key?: boolean;
}

export function splitProvidersByTier(providers: EligibleProvider[]): {
  freeProviders: EligibleProvider[];
  proProviders: EligibleProvider[];
} {
  const freeProviders: EligibleProvider[] = [];
  const proProviders: EligibleProvider[] = [];
  for (const provider of providers) {
    const freeModels = provider.models.filter((model) => model.is_free);
    const proModels = provider.is_free_tier
      ? provider.models
      : provider.models.filter((model) => !model.is_free);
    if (freeModels.length > 0 || provider.is_free_tier) {
      freeProviders.push({ ...provider, models: freeModels });
    }
    if (
      proModels.length > 0 &&
      (provider.has_api_key ||
        provider.require_api_key === false ||
        provider.is_custom ||
        provider.is_local)
    ) {
      proProviders.push({ ...provider, models: proModels });
    }
  }
  return { freeProviders, proProviders };
}

export function modelKey(providerId: string, modelId: string): string {
  return `${providerId}:${modelId}`;
}

export function buildEligibleProviders(
  providers: ProviderInfo[],
): EligibleProvider[] {
  return providers
    .filter((provider) => {
      const hasModels =
        (provider.models?.length ?? 0) + (provider.extra_models?.length ?? 0) >
        0;
      if (provider.is_free_tier) return true;
      if (!hasModels) return false;
      if (provider.require_api_key === false) return Boolean(provider.base_url);
      if (provider.is_custom) return Boolean(provider.base_url);
      if (provider.require_api_key ?? true) return Boolean(provider.api_key);
      return true;
    })
    .map((provider) => ({
      id: provider.id,
      name: provider.name,
      models: [
        ...(provider.models ?? []),
        ...(provider.extra_models ?? []),
      ].filter(
        (model) => !(provider.hidden_model_ids ?? []).includes(model.id),
      ),
      is_free_tier: provider.is_free_tier,
      is_custom: provider.is_custom,
      is_local: provider.is_local,
      supports_oauth: provider.supports_oauth,
      oauth_connected: provider.oauth_connected,
      has_api_key: Boolean(provider.api_key),
      require_api_key: provider.require_api_key,
    }));
}
