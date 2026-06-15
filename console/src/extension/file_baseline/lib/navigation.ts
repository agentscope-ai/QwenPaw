export function resolveFileBaselineDriftDeepLink(
  payload: Record<string, unknown>,
): string | null {
  const deepLink =
    typeof payload.deep_link === "string" ? payload.deep_link : null;
  if (deepLink) {
    return deepLink;
  }
  const alertId =
    typeof payload.alert_id === "string" ? payload.alert_id : null;
  if (alertId) {
    return `/security?tab=integrityProtection&fileBaselineAlertId=${encodeURIComponent(alertId)}`;
  }
  return null;
}

export function resolveFileBaselineDriftNavigation(
  eventType: string | undefined,
  payload: unknown,
): string | null {
  if ((eventType || "").toLowerCase() !== "file_baseline_drift") {
    return null;
  }
  if (!payload || typeof payload !== "object") {
    return null;
  }
  return resolveFileBaselineDriftDeepLink(payload as Record<string, unknown>);
}
