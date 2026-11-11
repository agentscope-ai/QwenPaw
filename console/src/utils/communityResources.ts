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

/** Skill vs plugin, tolerating cloud refs that carry only a `type`. */
export const reportResourceKind = (item: ReportResource): "skill" | "plugin" =>
  (item.origin?.resource_type ?? item.type) === "skill" ? "skill" : "plugin";

/**
 * Identity that works for both installed origins and cloud-restored refs so
 * the picker, tags and payload split never dereference a missing origin.
 */
export const reportResourceIdentity = (item: ReportResource) =>
  item.origin
    ? communityResourceIdentity(item.origin)
    : `${reportResourceKind(item)}:${item.related_id ?? ""}`;

/**
 * Split resources for a publish/save request: verified installations go to
 * `origins` (re-checked by the backend), cloud-restored refs go to `related`
 * (passed through verbatim).
 */
export function splitReportResources(resources: ReportResource[]): {
  origins: InstallationOrigin[];
  related: { type: "skill" | "plugin"; id: string }[];
} {
  const origins: InstallationOrigin[] = [];
  const related: { type: "skill" | "plugin"; id: string }[] = [];
  for (const item of resources) {
    if (item.origin) origins.push(item.origin);
    else if (item.related_id)
      related.push({ type: reportResourceKind(item), id: item.related_id });
  }
  return { origins, related };
}

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
