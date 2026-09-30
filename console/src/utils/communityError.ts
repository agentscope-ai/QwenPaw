/** Map sanitized community failures to actionable text without leaking responses. */
export function communityErrorKey(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error || "");
  const codes: Record<string, string> = {
    authorization_expired: "expired",
    community_login_required: "loginRequired",
    not_connected: "loginRequired",
    permission_not_granted: "permission",
    rate_limited: "rateLimited",
    messages_not_configured: "disabled",
    connection_changed: "connectionChanged",
    invalid_authorization_url: "invalidAuthorization",
    popup_blocked: "popupBlocked",
    unsupported_remote: "remote",
    external_open_failed: "openFailed",
    platform_unavailable: "service",
    network_unavailable: "network",
  };
  for (const [code, key] of Object.entries(codes)) {
    if (message.includes(code)) return `communityErrors.${key}`;
  }
  if (/fetch|network|offline|timeout|load failed/i.test(message))
    return "communityErrors.network";
  return "communityErrors.unavailable";
}
