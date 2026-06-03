import type { ProviderInfo } from "../../../api/types/provider";

/** Determine if a provider has valid credentials configured. */
export function getIsConfigured(provider: ProviderInfo): boolean {
  if (provider.id === "qwenpaw-local") return true;
  if (provider.is_custom && provider.base_url) return true;
  if (provider.require_api_key === false) return true;
  if (provider.require_api_key && provider.api_key) return true;
  return false;
}
