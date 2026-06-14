/** Fix ids that need a high-risk confirmation modal before running. */
export const HIGH_RISK_FIX_IDS = new Set([
  "seed-missing-agent-json",
  "reset-invalid-agent-json",
  "rebuild-console-npm",
  "write-empty-jobs-json",
  "normalize-jobs-cron",
]);

/** Reserved scan item ids — not shown in the health check table. */
export const RESERVED_SCAN_ITEM_IDS = new Set([
  "active-llm-connectivity",
  "api-health",
  "api-version",
  "console-over-http",
]);

export function isHighRiskFix(fixId: string): boolean {
  return HIGH_RISK_FIX_IDS.has(fixId);
}

export function canShowFixAction(
  fixId: string | null | undefined,
  status: string,
): fixId is string {
  return Boolean(fixId) && status !== "ok" && status !== "skipped";
}
