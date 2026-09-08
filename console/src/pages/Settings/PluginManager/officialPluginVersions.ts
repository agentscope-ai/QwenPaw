import type { OfficialPluginCatalogEntry } from "@/api/modules/plugin";
import { compareVersions } from "@/layouts/constants";

export interface OfficialPluginGroup {
  key: string;
  versions: OfficialPluginCatalogEntry[];
  defaultVersion: OfficialPluginCatalogEntry;
  installedVersion?: string;
}

export type OfficialPluginInstallAction =
  | "install"
  | "upgrade"
  | "reinstall"
  | "downgrade"
  | "current";

export type OfficialPluginVersionRelation =
  | "available"
  | "installed"
  | "upgrade"
  | "downgrade";

export interface OfficialPluginVersionOption {
  version: string;
  relation: OfficialPluginVersionRelation;
}

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

export function getOfficialPluginVersionOptions(
  group: OfficialPluginGroup,
): OfficialPluginVersionOption[] {
  const { installedVersion } = group;
  const options = group.versions.map((entry) => {
    if (!installedVersion) {
      return { version: entry.version, relation: "available" as const };
    }

    const comparison = compareVersions(entry.version, installedVersion);
    const relation: OfficialPluginVersionRelation =
      comparison > 0 ? "upgrade" : comparison < 0 ? "downgrade" : "installed";
    return { version: entry.version, relation };
  });

  if (
    installedVersion &&
    !options.some((option) => option.version === installedVersion)
  ) {
    options.unshift({ version: installedVersion, relation: "installed" });
  }

  return options;
}

export function resolveOfficialPluginSelection(
  group: OfficialPluginGroup,
  requestedVersion?: string,
): OfficialPluginSelection {
  const options = getOfficialPluginVersionOptions(group);
  const requestedSelection = options.some(
    (option) => option.version === requestedVersion,
  )
    ? requestedVersion
    : undefined;
  const selectedVersion =
    requestedSelection ??
    group.installedVersion ??
    group.defaultVersion.version;
  const catalogEntry = group.versions.find(
    (entry) => entry.version === selectedVersion,
  );

  let action: OfficialPluginInstallAction = "install";
  if (!catalogEntry) {
    action = "current";
  } else if (group.installedVersion) {
    const comparison = compareVersions(selectedVersion, group.installedVersion);
    action =
      comparison > 0 ? "upgrade" : comparison < 0 ? "downgrade" : "reinstall";
  }

  return {
    selectedVersion,
    catalogEntry,
    displayEntry: catalogEntry ?? group.defaultVersion,
    action,
    installedVersion: group.installedVersion,
  };
}
