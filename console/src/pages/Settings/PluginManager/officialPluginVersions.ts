import type { OfficialPluginCatalogEntry } from "@/api/modules/plugin";
import { compareVersions } from "@/layouts/constants";

export interface OfficialPluginGroup {
  key: string;
  versions: OfficialPluginCatalogEntry[];
  defaultVersion: OfficialPluginCatalogEntry;
}

export type OfficialPluginInstallAction =
  | "install"
  | "upgrade"
  | "reinstall"
  | "downgrade";

export function groupOfficialPlugins(
  entries: OfficialPluginCatalogEntry[],
): OfficialPluginGroup[] {
  const groups = new Map<string, OfficialPluginCatalogEntry[]>();

  entries.forEach((entry) => {
    const normalizedName = entry.name.trim().toLocaleLowerCase();
    const groupKey = normalizedName
      ? `name:${normalizedName}`
      : `id:${entry.plugin_id || entry.id}`;
    const versions = groups.get(groupKey);
    if (versions) {
      versions.push(entry);
    } else {
      groups.set(groupKey, [entry]);
    }
  });

  return [...groups.entries()].map(([key, versions]) => {
    const sortedVersions = [...versions].sort((a, b) =>
      compareVersions(b.version, a.version),
    );
    return {
      key,
      versions: sortedVersions,
      defaultVersion: sortedVersions[0],
    };
  });
}

export function getOfficialPluginInstallAction(
  entry: OfficialPluginCatalogEntry,
): OfficialPluginInstallAction {
  if (!entry.installed && !entry.installed_version) {
    return "install";
  }
  if (!entry.installed_version) {
    return "reinstall";
  }

  const comparison = compareVersions(entry.version, entry.installed_version);
  if (comparison > 0) return "upgrade";
  if (comparison < 0) return "downgrade";
  return "reinstall";
}
