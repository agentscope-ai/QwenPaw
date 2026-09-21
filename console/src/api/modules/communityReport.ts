import { request } from "../request";

export interface CommunityReportInput {
  resource_name: string;
  resource_type: "plugin" | "app" | "skill";
  installed_version: string;
  draft: string;
  logs: string;
  screenshots: { data_url: string }[];
  materials_reviewed: boolean;
  language: "zh" | "en";
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
