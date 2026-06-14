import type { HealthCheckItem } from "../api/client";

export const CAROUSEL_DISPLAY_DURATION_MS = 1800;
export const TERMINAL_SCAN_STATES = ["completed", "failed", "cancelled", "interrupted"];
export const TERMINAL_CAROUSEL_KEYS: Record<string, string> = {
  completed: "security.healthCheck.carousel.completed",
  failed: "security.healthCheck.carousel.failed",
  cancelled: "security.healthCheck.carousel.cancelled",
  interrupted: "security.healthCheck.carousel.interrupted",
};

export type HealthCheckRecord = Record<string, unknown>;

export function getString(
  record: HealthCheckRecord | HealthCheckItem | undefined,
  key: string,
): string {
  const value = (record as HealthCheckRecord | undefined)?.[key];
  return typeof value === "string" ? value : "";
}
