import type { MarketPluginEntry } from "@/api/modules/pluginMarket";
import { compareVersions } from "@/layouts/constants";
import {
  findMatchingInstalledPlugin,
  normalizeMarketPluginId,
  type InstalledPluginIdentity,
} from "./marketPluginIdentity";

export type MarketAppState = "available" | "installed" | "update";

/**
 * Return the installed version for a market entry when its IDs match.
 *
 * PawApp manifests currently store an unscoped app ID, while market entries
 * use the namespaced ``@owner/name`` form. App entries therefore use the
 * unscoped app ID as the stable local identity; regular plugin entries keep
 * the stricter owner-aware matching in ``marketPluginIdentity``.
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
  if (channel === "official" || channel === "app") {
    // PawApp IDs are unscoped locally (e.g. ``agent-kanban``), and the market
    // owner/author labels are not guaranteed to use the same naming scheme.
    const localAppId = normalizedId.split("/").pop() ?? normalizedId;
    const localApp = installedPluginList.find(
      (plugin) =>
        normalizeMarketPluginId(plugin.id) ===
        normalizeMarketPluginId(localAppId),
    );
    if (localApp?.version !== undefined) return localApp.version;
    exactIds.push(localAppId);
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
