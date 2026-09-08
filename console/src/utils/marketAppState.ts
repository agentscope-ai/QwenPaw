import type { MarketPluginEntry } from "@/api/modules/pluginMarket";
import { compareVersions } from "@/layouts/constants";
import {
  findMatchingInstalledPlugin,
  type InstalledPluginIdentity,
} from "./marketPluginIdentity";

export type MarketAppState = "available" | "installed" | "update";

/**
 * Return the installed version for a market entry when its IDs match.
 *
 * Community entries are namespaced by owner. An unscoped installed ID is only
 * accepted when its author agrees with the market owner or developer, because
 * two owners may publish apps with the same repository name.
 */
export function getInstalledMarketAppVersion(
  entry: MarketPluginEntry,
  installedAppVersions: ReadonlyMap<string, string>,
  channel: "official" | "community" | "app" = "community",
  installedPlugins: Iterable<InstalledPluginIdentity> = [],
): string | null {
  const installedPluginList = Array.from(installedPlugins);
  const matchedPlugin = findMatchingInstalledPlugin(entry, installedPluginList);
  if (matchedPlugin?.version !== undefined) return matchedPlugin.version;

  const normalizedId = entry.id.startsWith("@") ? entry.id.slice(1) : entry.id;
  const exactIds = [entry.id, normalizedId];
  if (
    (channel === "official" || channel === "app") &&
    installedPluginList.length === 0
  ) {
    // Keep compatibility for callers that only have a legacy version map.
    exactIds.push(normalizedId.split("/").pop() ?? normalizedId);
  }

  for (const id of exactIds) {
    const version = installedAppVersions.get(id);
    if (version !== undefined) return version;
  }
  return null;
}

export function getMarketAppState(
  entry: MarketPluginEntry,
  installedAppVersions: ReadonlyMap<string, string>,
  channel: "official" | "community" | "app" = "community",
  installedPlugins: Iterable<InstalledPluginIdentity> = [],
): MarketAppState {
  const installedVersion = getInstalledMarketAppVersion(
    entry,
    installedAppVersions,
    channel,
    installedPlugins,
  );
  if (installedVersion === null) return "available";
  return compareVersions(entry.version, installedVersion) !== 0
    ? "update"
    : "installed";
}
