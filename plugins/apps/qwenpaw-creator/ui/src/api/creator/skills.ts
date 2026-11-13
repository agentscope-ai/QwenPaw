import { creatorRequest, jsonBody } from "./client";

export interface SkillItem {
  name: string;
  description: string | null;
  enabled: boolean;
  status: "available" | "unavailable";
  reason: string | null;
  builtin: boolean;
}

export interface SkillContent {
  ok: boolean;
  skill: string;
  content: string;
  truncated: boolean;
}

export function listSkills(): Promise<{ items: SkillItem[] }> {
  return creatorRequest<{ items: SkillItem[] }>("/skills");
}

export function getSkillContent(name: string): Promise<SkillContent> {
  return creatorRequest<SkillContent>(
    `/skills/${encodeURIComponent(name)}/content`,
  );
}

export function saveSkill(
  name: string,
  content: string,
  // Replaces an existing same-named skill when true. Creating a skill must
  // leave it false: the backend then refuses a duplicate name instead of
  // overwriting the skill that already owns it.
  overwrite = false,
): Promise<{ ok: boolean; name: string }> {
  return creatorRequest<{ ok: boolean; name: string }>("/skills", {
    method: "POST",
    body: jsonBody({ name, content, overwrite }),
  });
}

export function setSkillEnabled(
  name: string,
  enabled: boolean,
): Promise<{ ok: boolean; name: string; enabled: boolean }> {
  return creatorRequest<{ ok: boolean; name: string; enabled: boolean }>(
    `/skills/${encodeURIComponent(name)}`,
    { method: "PATCH", body: jsonBody({ enabled }) },
  );
}

export function deleteSkill(name: string): Promise<{ deleted: string }> {
  return creatorRequest<{ deleted: string }>(
    `/skills/${encodeURIComponent(name)}`,
    { method: "DELETE" },
  );
}

export interface SkillImportResult {
  imported: string[];
  skipped: Array<{ name: string; reason: string }>;
  count: number;
}

export function uploadSkillZip(file: File): Promise<SkillImportResult> {
  const form = new FormData();
  form.append("file", file);
  return creatorRequest<SkillImportResult>("/skills/upload", {
    method: "POST",
    body: form,
  });
}

export interface SkillUrlImportResult extends SkillImportResult {
  name: string;
  // The market name when it had to be folded into a valid slug, else null.
  renamed_from: string | null;
  source_url: string;
  installed_from: string;
  // references/scripts/extra_files dropped by design: a Creator skill is
  // only its SKILL.md text.
  ignored_files: number;
}

export function importSkillFromUrl(
  bundleUrl: string,
  targetName?: string,
): Promise<SkillUrlImportResult> {
  return creatorRequest<SkillUrlImportResult>(
    "/skills/import-url",
    {
      method: "POST",
      body: jsonBody({
        bundle_url: bundleUrl,
        target_name: (targetName || "").trim() || null,
      }),
    },
    // The server budgets 90s for one market download, so give up a little
    // after it: the backend's own timeout explanation beats a bare 408.
    { timeoutMs: 100_000 },
  );
}

// ── Market search ───────────────────────────────────────────────────────────

export interface MarketSkillResult {
  source: string;
  source_label: string | null;
  slug: string;
  name: string;
  description: string | null;
  source_url: string;
  version: string | null;
  author: string | null;
  icon_url: string | null;
  stats: Record<string, string | number> | null;
}

export interface MarketSearchResponse {
  results: MarketSkillResult[];
  has_more: boolean;
  totals: Record<string, number>;
}

export function searchMarketSkills(
  query: string,
  page = 1,
  limit = 20,
  lang = "en",
): Promise<MarketSearchResponse> {
  const params = new URLSearchParams();
  if (query) params.set("query", query);
  params.set("page", String(page));
  params.set("limit", String(limit));
  params.set("lang", lang);
  return creatorRequest<MarketSearchResponse>(
    `/skills/market/search?${params.toString()}`,
  );
}

export interface MarketProvider {
  key: string;
  label: string;
  available: boolean;
  reason: string | null;
  supports_browse: boolean;
}

export function listMarketProviders(): Promise<{ providers: MarketProvider[] }> {
  return creatorRequest<{ providers: MarketProvider[] }>(
    "/skills/market/providers",
  );
}
