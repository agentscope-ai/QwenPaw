import { clearAuthToken, getApiToken, getApiUrl } from "../config";
import { responseErrorMessage } from "../error";

export interface HubUser {
  user_id: string;
  username: string;
  role: "admin" | "user";
  disabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface HubRuntime {
  runtime_id: string;
  tenant_id: string;
  owner_user_id: string;
  provisioner: string;
  host: string;
  port: number;
  state: "created" | "starting" | "running" | "stopped" | "failed";
  endpoint: string;
  security_level: string;
  last_error?: string | null;
  created_at: string;
  updated_at: string;
}

export interface HubCredential {
  scope: string;
  name: string;
  created_at: string;
  updated_at: string;
}

export interface HubPage<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
  pages: number;
}

export interface HubListParams {
  page?: number;
  pageSize?: number;
  query?: string;
}

export interface HubRuntimeListParams extends HubListParams {
  state?: HubRuntime["state"];
  provisioner?: string;
  owner?: string;
}

export interface HubUserListParams extends HubListParams {
  role?: HubUser["role"];
  disabled?: boolean;
}

export interface HubCredentialListParams extends HubListParams {
  scope?: string;
}

export interface HubAuditEvent {
  event_id: string;
  actor_user_id: string;
  actor_username: string;
  action: string;
  resource_type: string;
  resource_id: string;
  outcome: string;
  detail: Record<string, unknown>;
  created_at: string;
}

export interface HubOverview {
  runtime_counts: Record<HubRuntime["state"], number>;
  total_runtimes: number;
  total_users: number;
  runtime_available: boolean;
  host: {
    cpu_percent: number;
    memory_percent: number;
    disk_percent: number;
  };
  recent_events: HubAuditEvent[];
}

export interface HubProvisionerStatus {
  available: boolean;
  reason?: string | null;
  security_level: string;
}

export interface HubHealth {
  status: "ok" | "degraded";
  mode: "hub";
  default_provisioner: string;
  runtime_available: boolean;
  provisioner_statuses: Record<string, HubProvisionerStatus>;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getApiToken();
  const response = await fetch(getApiUrl(path), {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...init?.headers,
    },
  });
  if (response.status === 401) {
    clearAuthToken();
    window.location.assign("/login");
    throw new Error("Authentication expired");
  }
  if (!response.ok) {
    throw new Error(
      await responseErrorMessage(
        response,
        `Request failed with ${response.status}`,
      ),
    );
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}

function listPath<T extends HubListParams>(path: string, params: T): string {
  const query = new URLSearchParams();
  if (params.page) query.set("page", String(params.page));
  if (params.pageSize) query.set("page_size", String(params.pageSize));
  if (params.query?.trim()) query.set("q", params.query.trim());
  Object.entries(params).forEach(([key, value]) => {
    if (["page", "pageSize", "query"].includes(key)) return;
    if (value !== undefined && value !== "") {
      query.set(key, String(value));
    }
  });
  const suffix = query.toString();
  return suffix ? `${path}?${suffix}` : path;
}

export const hubApi = {
  getHealth: () => request<HubHealth>("/hub/healthz"),
  me: () => request<HubUser>("/hub/me"),
  listRuntimes: (params: HubRuntimeListParams = {}) =>
    request<HubPage<HubRuntime>>(listPath("/hub/runtimes", params)),
  createRuntime: (runtimeId: string, autoStart = false) =>
    request<HubRuntime>("/hub/runtimes", {
      method: "POST",
      body: JSON.stringify({ runtime_id: runtimeId, auto_start: autoStart }),
    }),
  startRuntime: (runtimeId: string) =>
    request<HubRuntime>(`/hub/runtimes/${runtimeId}/start`, {
      method: "POST",
    }),
  stopRuntime: (runtimeId: string) =>
    request<HubRuntime>(`/hub/runtimes/${runtimeId}/stop`, {
      method: "POST",
    }),
  deleteRuntime: (runtimeId: string) =>
    request<void>(`/hub/runtimes/${runtimeId}`, { method: "DELETE" }),
  listUsers: (params: HubUserListParams = {}) =>
    request<HubPage<HubUser>>(listPath("/hub/admin/users", params)),
  createUser: (username: string, password: string, role: HubUser["role"]) =>
    request<HubUser>("/hub/admin/users", {
      method: "POST",
      body: JSON.stringify({ username, password, role }),
    }),
  updateUser: (
    userId: string,
    patch: Partial<Pick<HubUser, "role" | "disabled">>,
  ) =>
    request<HubUser>(`/hub/admin/users/${userId}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  getRegistration: () =>
    request<{ enabled: boolean }>("/hub/admin/settings/registration"),
  setRegistration: (enabled: boolean) =>
    request<{ enabled: boolean }>("/hub/admin/settings/registration", {
      method: "PUT",
      body: JSON.stringify({ enabled }),
    }),
  listCredentials: (params: HubCredentialListParams = {}) =>
    request<HubPage<HubCredential>>(listPath("/hub/credentials", params)),
  putCredential: (scope: string, name: string, value: string) =>
    request<void>("/hub/credentials", {
      method: "PUT",
      body: JSON.stringify({ scope, name, value }),
    }),
  deleteCredential: (scope: string, name: string) =>
    request<void>(
      `/hub/credentials/${encodeURIComponent(scope)}/${encodeURIComponent(
        name,
      )}`,
      { method: "DELETE" },
    ),
  getOverview: () => request<HubOverview>("/hub/admin/overview"),
  listAuditEvents: (params: HubListParams & { action?: string } = {}) =>
    request<HubPage<HubAuditEvent>>(listPath("/hub/admin/audit", params)),
};
