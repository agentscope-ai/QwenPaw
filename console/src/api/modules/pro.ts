import { clearAuthToken, getApiToken, getApiUrl } from "../config";
import { responseErrorMessage } from "../error";

export interface ProUser {
  user_id: string;
  username: string;
  role: "admin" | "user";
  disabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface ProRuntime {
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

export interface ProCredential {
  scope: string;
  name: string;
  created_at: string;
  updated_at: string;
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

export const proApi = {
  me: () => request<ProUser>("/pro/me"),
  listRuntimes: () => request<ProRuntime[]>("/pro/runtimes"),
  createRuntime: (runtimeId: string, autoStart = false) =>
    request<ProRuntime>("/pro/runtimes", {
      method: "POST",
      body: JSON.stringify({ runtime_id: runtimeId, auto_start: autoStart }),
    }),
  startRuntime: (runtimeId: string) =>
    request<ProRuntime>(`/pro/runtimes/${runtimeId}/start`, {
      method: "POST",
    }),
  stopRuntime: (runtimeId: string) =>
    request<ProRuntime>(`/pro/runtimes/${runtimeId}/stop`, {
      method: "POST",
    }),
  deleteRuntime: (runtimeId: string) =>
    request<void>(`/pro/runtimes/${runtimeId}`, { method: "DELETE" }),
  listUsers: () => request<ProUser[]>("/pro/admin/users"),
  createUser: (username: string, password: string, role: ProUser["role"]) =>
    request<ProUser>("/pro/admin/users", {
      method: "POST",
      body: JSON.stringify({ username, password, role }),
    }),
  updateUser: (
    userId: string,
    patch: Partial<Pick<ProUser, "role" | "disabled">>,
  ) =>
    request<ProUser>(`/pro/admin/users/${userId}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  getRegistration: () =>
    request<{ enabled: boolean }>("/pro/admin/settings/registration"),
  setRegistration: (enabled: boolean) =>
    request<{ enabled: boolean }>("/pro/admin/settings/registration", {
      method: "PUT",
      body: JSON.stringify({ enabled }),
    }),
  listCredentials: () => request<ProCredential[]>("/pro/credentials"),
  putCredential: (scope: string, name: string, value: string) =>
    request<void>("/pro/credentials", {
      method: "PUT",
      body: JSON.stringify({ scope, name, value }),
    }),
  deleteCredential: (scope: string, name: string) =>
    request<void>(
      `/pro/credentials/${encodeURIComponent(scope)}/${encodeURIComponent(
        name,
      )}`,
      { method: "DELETE" },
    ),
};
