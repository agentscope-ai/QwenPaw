import type { PluginInfo } from "@/api/modules/plugin";
import type { MarketPluginEntry } from "@/api/modules/pluginMarket";

export interface InstalledPluginIdentity {
  id: string;
  author?: string;
  version?: string;
}

export function normalizeMarketPluginId(id: string): string {
  return id.trim().replace(/^@/, "").toLowerCase();
}

function marketPluginName(id: string): string {
  const normalized = normalizeMarketPluginId(id);
  return normalized.slice(normalized.lastIndexOf("/") + 1);
}

function normalizeAuthor(author: string | undefined): string {
  return author?.trim().replace(/^@/, "").toLowerCase() ?? "";
}

/** Match a local plugin to a market entry without unsafe short-name matches. */
export function marketPluginMatches(
  plugin: InstalledPluginIdentity | PluginInfo,
  entry: MarketPluginEntry,
): boolean {
  const pluginId = normalizeMarketPluginId(plugin.id);
  const marketId = normalizeMarketPluginId(entry.id);
  if (pluginId === marketId) return true;
  if (pluginId !== marketPluginName(marketId)) return false;

  const author = normalizeAuthor(plugin.author);
  if (!author) return false;
  return [entry.owner, entry.developer].some(
    (owner) => normalizeAuthor(owner) === author,
  );
}

export function findMatchingInstalledPlugin(
  entry: MarketPluginEntry,
  plugins: Iterable<InstalledPluginIdentity>,
): InstalledPluginIdentity | undefined {
  for (const plugin of plugins) {
    if (marketPluginMatches(plugin, entry)) return plugin;
  }
  return undefined;
}
