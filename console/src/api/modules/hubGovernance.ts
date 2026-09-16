import type { BaseUrlOption, ModelInfo } from "../types";
import { getApiToken, getApiUrl } from "../config";
import { responseErrorMessage } from "../error";

export async function governanceRequest<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const response = await fetch(getApiUrl(`/hub/${path}`), {
    method,
    headers: {
      Authorization: `Bearer ${getApiToken()}`,
      "Content-Type": "application/json",
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok)
    throw new Error(await responseErrorMessage(response, "Hub request failed"));
  return response.status === 204 ? (undefined as T) : response.json();
}

export interface ModelPolicy {
  default_model_id: string | null;
  member_token_limit: number | null;
  timezone: string;
  revision: number;
}
export interface ModelProviderPreset {
  id: string;
  name: string;
  base_url: string;
  api_key_prefix: string;
  api_key_prefixes?: string[];
  freeze_url: boolean;
  base_url_options: BaseUrlOption[];
  models: ModelInfo[];
}

export interface ModelConnection {
  provider_id?: string | null;
  id: string;
  name: string;
  base_url: string;
  enabled: boolean;
  quota_scope: string;
  requests_per_minute: number;
  concurrency: number;
  has_key: boolean;
  revision: number;
}
export interface ManagedModel {
  id: string;
  name: string;
  description: string;
  connection_id: string;
  upstream_model: string;
  enabled: boolean;
  all_members: boolean;
  user_ids: string[];
  input_token_limit: number;
  output_token_limit: number;
  output_limit_field: string;
  budget_verified: boolean;
  supports_image: boolean | null;
  requests_per_minute: number;
  concurrency: number;
  revision: number;
}
export interface BudgetUsage {
  subject: string;
  period: string;
  token_limit: number | null;
  remaining: number | null;
  charged: number;
  actual: number;
  reserved: number;
  conservative: number;
  requests: number;
}
export interface UsageReport {
  timezone: string;
  daily: { date: string; tokens: number }[];
  organization: BudgetUsage;
  members: (BudgetUsage & {
    user_id: string;
    username: string;
    inherits_budget: boolean;
    runtime_states: string[];
  })[];
  models: {
    model_id: string;
    requests: number;
    charged: number;
    failures: number;
  }[];
}
export interface InviteBatch {
  id: string;
  note: string;
  total: number;
  redeemed: number;
  revoked: number;
  expires_at: string;
}

export interface MemberModelCatalog {
  revision: number;
  default_model_id: string | null;
  models: {
    id: string;
    name: string;
    description: string;
    supports_image: boolean | null;
    input_token_limit: number;
    output_token_limit: number;
  }[];
}

export interface UsageDetailRow {
  date: string;
  user_id: string;
  username: string;
  model_id: string;
  model_name: string;
  requests: number;
  charged: number;
  actual: number;
  reserved: number;
  conservative: number;
  failures: number;
}
export interface UsageDetails {
  timezone: string;
  rows: UsageDetailRow[];
}
