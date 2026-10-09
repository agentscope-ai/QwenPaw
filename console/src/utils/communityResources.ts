import type { InstallationOrigin } from "@/api/types/community";
import type { ReportResource } from "@/api/modules/communityReport";
import type { MarketResult } from "@/api/modules/market";
import {
  isMarketPluginApp,
  type MarketPluginEntry,
} from "@/api/modules/pluginMarket";

/** Apps and plugins share a Platform collection and must not be linked twice. */
export const communityResourceIdentity = (origin: InstallationOrigin) =>
  `${origin.resource_type === "skill" ? "skill" : "plugin"}:${
    origin.resource_id
  }`;

function marketOrigin(
  id: string,
  type: InstallationOrigin["resource_type"],
): InstallationOrigin | undefined {
  const match = /^@?([A-Za-z0-9_.-]+)\/([A-Za-z0-9_.-]+)$/.exec(id);
  if (!match || match.slice(1).some((part) => part === "." || part === ".."))
    return;
  const resourceId = `@${match[1]}/${match[2]}`;
  return {
    provider: "agentscope-platform",
    resource_type: type,
    resource_id: resourceId,
    source_url: `https://platform.agentscope.io/${
      type === "skill" ? "skills" : "plugins"
    }/${resourceId}`,
  };
}

export function pluginMarketResource(
  entry: MarketPluginEntry,
): ReportResource | undefined {
  const origin = marketOrigin(
    entry.id,
    isMarketPluginApp(entry) ? "app" : "plugin",
  );
  if (!origin) return;
  return {
    origin,
    name: entry.display_name,
    description:
      entry.locales?.zh?.description || entry.locales?.en?.description,
  };
}

export function skillMarketResource(
  entry: MarketResult,
): ReportResource | undefined {
  if (entry.source !== "qwenpaw") return;
  const origin = marketOrigin(entry.slug, "skill");
  if (!origin) return;
  return {
    origin,
    name: entry.name,
    description: entry.description || undefined,
  };
}
