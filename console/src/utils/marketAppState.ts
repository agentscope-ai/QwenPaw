import type { MarketPluginEntry } from "@/api/modules/pluginMarket";
import { compareVersions } from "@/layouts/constants";

export type MarketAppState = "available" | "installed" | "update";

/**
 * Return the installed version for a market entry when its IDs match.
 *
 * Community entries are namespaced by owner. Their short name is therefore
 * intentionally not used as a fallback, because two owners may publish apps
 * with the same repository name. Official entries retain the short-name
 * fallback for compatibility with the bundled app IDs.
 */
export function getInstalledMarketAppVersion(
  entry: MarketPluginEntry,
  installedAppVersions: ReadonlyMap<string, string>,
  channel: "official" | "community" = "community",
): string | null {
  const normalizedId = entry.id.startsWith("@") ? entry.id.slice(1) : entry.id;
  const exactIds = [entry.id, normalizedId];
  if (channel === "official") {
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
  channel: "official" | "community" = "community",
): MarketAppState {
  const installedVersion = getInstalledMarketAppVersion(
    entry,
    installedAppVersions,
    channel,
  );
  if (installedVersion === null) return "available";
  return compareVersions(entry.version, installedVersion) !== 0
    ? "update"
    : "installed";
}
