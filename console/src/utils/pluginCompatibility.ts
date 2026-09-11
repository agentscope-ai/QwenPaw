import type { MarketPluginEntry } from "@/api/modules/pluginMarket";

function deriveCompatLabel(version: string): string | null {
  const trimmed = version.trim().replace(/^v/i, "");
  const match = trimmed.match(/^(\d+)/);
  if (!match) return null;
  return `${match[1]}.x`;
}

export function isMarketPluginCompatible(
  entry: MarketPluginEntry,
  currentVersion: string | null,
): boolean {
  if (!currentVersion) return true;
  const labels = entry.qwenpaw_compat_labels;
  if (!labels || labels.length === 0) return true;
  const label = deriveCompatLabel(currentVersion);
  if (!label) return true;
  return labels.includes(label);
}
