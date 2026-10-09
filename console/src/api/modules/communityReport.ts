import type { InstallationOrigin } from "../types/community";
import { request } from "../request";

export interface CommunityReportInput {
  agent_id?: string;
  history?: { role: "user" | "assistant"; content: string }[];
  article_type?: string;
  resource_context?: string;
  resource_name: string;
  resource_type: "plugin" | "app" | "skill";
  installed_version: string;
  draft: string;
  instructions?: string;
  writing_style?: "auto" | "concise" | "detailed";
  logs: string;
  screenshots: { data_url: string }[];
  materials_reviewed: boolean;
  language: "zh" | "en" | "auto";
}

export function generateCommunityReport(
  body: CommunityReportInput,
  signal: AbortSignal,
): Promise<{ report: string }> {
  return request("/community/report/generate", {
    method: "POST",
    body: JSON.stringify(body),
    timeout: 125_000,
    signal,
  });
}

export interface ReportResource {
  name: string;
  local_id?: string;
  origin: InstallationOrigin;
  description?: string;
  status?: Record<string, unknown>;
}
export const reportResourceKey = (origin: InstallationOrigin) =>
  `${origin.resource_type}:${origin.resource_id}`;

export interface DiagnosticEvidence {
  id: string;
  content: string;
}
export function collectCommunityDiagnostics(
  origins: InstallationOrigin[],
  minutes: number,
  session_id: string,
  agentId: string | undefined,
  signal: AbortSignal,
): Promise<{ evidence: DiagnosticEvidence[]; warnings: string[] }> {
  return request("/community/report/diagnostics", {
    method: "POST",
    body: JSON.stringify({ origins, minutes, session_id }),
    headers: agentId ? { "X-Agent-Id": agentId } : undefined,
    signal,
  });
}

interface PluginCommunityLinks {
  resources: ReportResource[];
  lookup_failed_ids?: string[];
}
let pluginLinks: Promise<PluginCommunityLinks> | undefined;
let pluginLinksUntil = 0;
/** Coalesce resource-card lookups without blocking the installed-plugin list. */
export function lookupInstalledPluginLinks(
  retry = false,
): Promise<PluginCommunityLinks> {
  if (retry || !pluginLinks || Date.now() >= pluginLinksUntil) {
    pluginLinksUntil = Date.now() + 30_000;
    const pending = request<PluginCommunityLinks>(
      "/community/report/resources",
    ).then((data) => ({
      ...data,
      resources: data.resources.filter(
        (item) => item.origin.resource_type !== "skill",
      ),
    }));
    pluginLinks = pending;
    void pending.catch(() => {
      if (pluginLinks === pending) {
        pluginLinks = undefined;
        pluginLinksUntil = 0;
      }
    });
  }
  return pluginLinks;
}
