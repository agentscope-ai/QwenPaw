export interface QwenPawAuthStatus {
  enabled: boolean;
  has_users: boolean;
}

export function requiresQwenPawCredentials(
  status: QwenPawAuthStatus,
): boolean {
  return status.enabled && status.has_users;
}
