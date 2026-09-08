import type { OfficialPluginCatalogEntry } from "@/api/modules/plugin";
import { compareVersions } from "@/layouts/constants";

export interface OfficialPluginGroup {
  key: string;
  versions: OfficialPluginCatalogEntry[];
  defaultVersion: OfficialPluginCatalogEntry;
  installedVersion?: string;
}

export type OfficialPluginInstallAction = "install" | "update" | "current";

export interface OfficialPluginSelection {
  selectedVersion: string;
  catalogEntry?: OfficialPluginCatalogEntry;
  displayEntry: OfficialPluginCatalogEntry;
  action: OfficialPluginInstallAction;
  installedVersion?: string;
}

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
    const installedVersion = sortedVersions
      .flatMap((entry) => {
        if (entry.installed_version) return [entry.installed_version];
        return entry.installed ? [entry.version] : [];
      })
      .sort((a, b) => compareVersions(b, a))[0];
    return {
      key,
      versions: sortedVersions,
      defaultVersion: sortedVersions[0],
      installedVersion,
    };
  });
}

export function getOfficialPluginVersions(
  group: OfficialPluginGroup,
): string[] {
  const versions = group.versions.map((entry) => entry.version);

  if (group.installedVersion && !versions.includes(group.installedVersion)) {
    versions.unshift(group.installedVersion);
  }

  return versions;
}

export function resolveOfficialPluginSelection(
  group: OfficialPluginGroup,
  requestedVersion?: string,
): OfficialPluginSelection {
  const versions = getOfficialPluginVersions(group);
  const latestVersion = group.defaultVersion.version;
  const updateAvailable = Boolean(
    group.installedVersion &&
      compareVersions(latestVersion, group.installedVersion) > 0,
  );

  if (updateAvailable) {
    return {
      selectedVersion: latestVersion,
      catalogEntry: group.defaultVersion,
      displayEntry: group.defaultVersion,
      action: "update",
      installedVersion: group.installedVersion,
    };
  }

  const requestedSelection = versions.includes(requestedVersion ?? "")
    ? requestedVersion
    : undefined;
  const selectedVersion =
    requestedSelection ??
    group.installedVersion ??
    group.defaultVersion.version;
  const catalogEntry = group.versions.find(
    (entry) => entry.version === selectedVersion,
  );

  const action: OfficialPluginInstallAction =
    group.installedVersion === selectedVersion
      ? "current"
      : catalogEntry
      ? "install"
      : "current";

  return {
    selectedVersion,
    catalogEntry,
    displayEntry: catalogEntry ?? group.defaultVersion,
    action,
    installedVersion: group.installedVersion,
  };
}
