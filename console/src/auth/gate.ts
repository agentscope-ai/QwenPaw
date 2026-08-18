import { authApi } from "../api/modules/auth";
import { clearAuthToken, getApiToken, getApiUrl } from "../api/config";

export type AuthGateState = "ok" | "auth-required";
export type BackendMode = "standard" | "pro";

export async function resolveBackendMode(): Promise<BackendMode> {
  const status = await authApi.getStatus();
  return status.mode === "pro" ? "pro" : "standard";
}

export async function resolveAuthGate(): Promise<AuthGateState> {
  const status = await authApi.getStatus();
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
