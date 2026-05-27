import { KNOWN_PLUGIN_PLATFORM_KINDS } from "./constants";
import type { DesktopIndex, FileMetadata, LocalizedText } from "./types";

export function pickLocalizedField(
  value: LocalizedText | undefined,
  language: string | undefined,
): string {
  if (!value) return "";
  const zh = value["zh-CN"]?.trim() ?? "";
  const en = value["en-US"]?.trim() ?? "";
  if (language?.startsWith("zh")) {
    return zh || en;
  }
  return en || zh;
}

export function isPreviewVersion(version: string): boolean {
  return /[ab]\d*$/i.test(version) || /preview/i.test(version);
}

function compareVersionPart(a: string, b: string): number {
  const aNum = Number(a);
  const bNum = Number(b);
  if (!Number.isNaN(aNum) && !Number.isNaN(bNum)) {
    return aNum - bNum;
  }
  return a.localeCompare(b);
}

export function compareVersionDesc(a: string, b: string): number {
  const aBase = a.match(/^\d+(?:\.\d+)*/)?.[0] ?? "0";
  const bBase = b.match(/^\d+(?:\.\d+)*/)?.[0] ?? "0";
  const aParts = aBase.split(".");
  const bParts = bBase.split(".");
  const maxLength = Math.max(aParts.length, bParts.length);

  for (let i = 0; i < maxLength; i += 1) {
    const result = compareVersionPart(aParts[i] ?? "0", bParts[i] ?? "0");
    if (result !== 0) {
      return -result;
    }
  }

  const aIsPreview = isPreviewVersion(a);
  const bIsPreview = isPreviewVersion(b);
  if (aIsPreview !== bIsPreview) {
    return aIsPreview ? 1 : -1;
  }

  return b.localeCompare(a);
}

export function latestFileIdByPluginId(
  files: FileMetadata[],
): Map<string, string> {
  const grouped = new Map<string, FileMetadata[]>();
  for (const file of files) {
    const pluginId = file.plugin_id ?? file.id;
    const list = grouped.get(pluginId) ?? [];
    list.push(file);
    grouped.set(pluginId, list);
  }

  const latest = new Map<string, string>();
  for (const [pluginId, versions] of grouped) {
    const sorted = [...versions].sort((a, b) =>
      compareVersionDesc(a.version, b.version),
    );
    const latestStable = sorted.find((item) => !isPreviewVersion(item.version));
    const chosen = latestStable ?? sorted[0];
    if (chosen) {
      latest.set(pluginId, chosen.id);
    }
  }
  return latest;
}

export function groupFilesByPluginId(
  files: FileMetadata[],
): Array<{ pluginId: string; versions: FileMetadata[] }> {
  const grouped = new Map<string, FileMetadata[]>();
  for (const file of files) {
    const pluginId = file.plugin_id ?? file.id;
    const list = grouped.get(pluginId) ?? [];
    list.push(file);
    grouped.set(pluginId, list);
  }

  return Array.from(grouped.entries())
    .map(([pluginId, versions]) => ({
      pluginId,
      versions: [...versions].sort((a, b) =>
        compareVersionDesc(a.version, b.version),
      ),
    }))
    .sort((a, b) => {
      const nameA = a.versions[0]?.name["en-US"] ?? a.pluginId;
      const nameB = b.versions[0]?.name["en-US"] ?? b.pluginId;
      return nameA.localeCompare(nameB);
    });
}

export function detectOS(): string | null {
  const userAgent = window.navigator.userAgent.toLowerCase();
  if (userAgent.includes("win")) return "win";
  if (userAgent.includes("mac")) return "mac";
  if (userAgent.includes("linux")) return "linux";
  return null;
}

export function formatPlatformKindLabel(kind: string): string {
  if (!kind) return "";
  return kind.charAt(0).toUpperCase() + kind.slice(1);
}

export function sortPluginPlatformKinds(kinds: string[]): string[] {
  const known = KNOWN_PLUGIN_PLATFORM_KINDS as readonly string[];
  return [...new Set(kinds)].sort((a, b) => {
    const aRank = known.indexOf(a);
    const bRank = known.indexOf(b);
    const aOrder = aRank === -1 ? Number.MAX_SAFE_INTEGER : aRank;
    const bOrder = bRank === -1 ? Number.MAX_SAFE_INTEGER : bRank;
    if (aOrder !== bOrder) return aOrder - bOrder;
    return a.localeCompare(b, undefined, { sensitivity: "base" });
  });
}

export function getPluginPlatformKinds(index: DesktopIndex): string[] {
  const kinds = new Set<string>();
  for (const key of Object.keys(index.platforms ?? {})) {
    kinds.add(key);
  }
  for (const file of Object.values(index.files ?? {})) {
    if (file.platform) kinds.add(file.platform);
  }
  return sortPluginPlatformKinds([...kinds]);
}
export function getFilesForPluginPlatform(
  index: DesktopIndex,
  platformKind: string,
): FileMetadata[] {
  const ids = new Set(index.platforms?.[platformKind]?.versions ?? []);
  for (const file of Object.values(index.files ?? {})) {
    if (file.platform === platformKind) ids.add(file.id);
  }
  return [...ids]
    .map((id) => index.files[id])
    .filter((item): item is FileMetadata => Boolean(item));
}

export function orderVersionsWithDefault(
  versions: FileMetadata[],
  defaultId: string | undefined,
): FileMetadata[] {
  const defaultVersion =
    versions.find((item) => item.id === defaultId) ?? versions[0];
  if (!defaultVersion) return versions;
  return [
    defaultVersion,
    ...versions.filter((item) => item.id !== defaultVersion.id),
  ];
}
