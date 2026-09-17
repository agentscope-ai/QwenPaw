import { authApi, type AuthStatusResponse } from "../api/modules/auth";
import { clearAuthToken, getApiToken, getApiUrl } from "../api/config";

export type AuthGateState = "ok" | "auth-required";
export type BackendMode = "standard" | "hub";

export interface BackendInfo {
  mode: BackendMode;
  authStatus: AuthStatusResponse;
}

export async function resolveBackendInfo(): Promise<BackendInfo> {
  const authStatus = await authApi.getStatus();
  return {
    mode: authStatus.mode === "hub" ? "hub" : "standard",
    authStatus,
  };
}

export async function resolveBackendMode(): Promise<BackendMode> {
  return (await resolveBackendInfo()).mode;
}

export async function resolveAuthGate(
  knownStatus?: AuthStatusResponse,
): Promise<AuthGateState> {
  const status = knownStatus ?? (await authApi.getStatus());
  if (!status.enabled) {
    return "ok";
  }

  const token = getApiToken();
  if (!token) {
    return "auth-required";
  }

  const response = await fetch(getApiUrl("/auth/verify"), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (response.ok) {
    return "ok";
  }
  if (response.status === 401 || response.status === 403) {
    clearAuthToken();
    return "auth-required";
  }
  throw new Error(`Authentication service returned ${response.status}`);
}
