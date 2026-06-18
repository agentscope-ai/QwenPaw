import type { ProviderInfo } from "../../../api/types/provider";

/** Determine if a provider has valid credentials configured. */
export function getIsConfigured(provider: ProviderInfo): boolean {
  if (provider.id === "qwenpaw-local") return true;
  if (provider.is_custom && provider.base_url) return true;
  if (provider.require_api_key === false) return true;
  if (provider.require_api_key && provider.api_key) return true;
  return false;
}

export interface ProviderGroup {
  groupKey: string;
  groupName: string;
  providers: ProviderInfo[];
}

/**
 * Split providers into grouped (same brand) and ungrouped lists.
 */
export function groupProviders(providers: ProviderInfo[]): {
  grouped: ProviderGroup[];
  ungrouped: ProviderInfo[];
} {
  const groupMap = new Map<string, ProviderGroup>();
  const ungrouped: ProviderInfo[] = [];

  for (const p of providers) {
    if (p.provider_group) {
      const existing = groupMap.get(p.provider_group);
      if (existing) {
        existing.providers.push(p);
      } else {
        groupMap.set(p.provider_group, {
          groupKey: p.provider_group,
          groupName: p.provider_group_name || p.provider_group,
          providers: [p],
        });
      }
    } else {
      ungrouped.push(p);
    }
  }

  const grouped: ProviderGroup[] = [];
  for (const g of groupMap.values()) {
    if (g.providers.length >= 2) {
      grouped.push(g);
    } else {
      ungrouped.push(...g.providers);
    }
  }

  return { grouped, ungrouped };
}
