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
  enabled: boolean;
  invitation_enabled: boolean;
  default_model_id: string | null;
  member_token_limit: number | null;
  timezone: string;
  revision: number;
}
export interface ModelConnection {
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
  supports_image: boolean;
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
  organization: BudgetUsage;
  members: (BudgetUsage & { user_id: string; username: string })[];
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
