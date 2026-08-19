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
  driver: string;
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

export interface HubDriverStatus {
  available: boolean;
  reason?: string | null;
  security_level: string;
}

export interface HubHealth {
  status: "ok" | "degraded";
  mode: "hub";
  default_driver: string;
  runtime_available: boolean;
  driver_statuses: Record<string, HubDriverStatus>;
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

export const hubApi = {
  getHealth: () => request<HubHealth>("/hub/healthz"),
  me: () => request<HubUser>("/hub/me"),
  listRuntimes: () => request<HubRuntime[]>("/hub/runtimes"),
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
  listUsers: () => request<HubUser[]>("/hub/admin/users"),
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
  listCredentials: () => request<HubCredential[]>("/hub/credentials"),
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
};
