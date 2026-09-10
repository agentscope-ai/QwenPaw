export interface QwenPawAuthStatus {
  bootstrap_required?: boolean;
  enabled: boolean;
  has_users: boolean;
  mode?: "hub";
  registration_enabled?: boolean;
}

export function requiresQwenPawCredentials(
  status: QwenPawAuthStatus,
): boolean {
  return status.mode === "hub" || (status.enabled && status.has_users);
}

export function shouldBootstrapHub(status: QwenPawAuthStatus): boolean {
  return status.mode === "hub" && Boolean(status.bootstrap_required);
}

export function qwenPawCredentialEndpoint(
  status: QwenPawAuthStatus | null,
): "/api/auth/login" | "/api/auth/register" {
  return status && shouldBootstrapHub(status)
    ? "/api/auth/register"
    : "/api/auth/login";
}
