import type { HealthCheckItem } from "../api/client";
import { getString, type HealthCheckRecord } from "./scanUi";

/** Security page tab keys reachable from health-check guidance. */
export type SecurityTabKey =
  | "toolGuard"
  | "fileGuard"
  | "skillScanner"
  | "integrityCheck";

export function resolveSecurityTabLink(
  record: HealthCheckRecord | HealthCheckItem,
): SecurityTabKey | null {
  const itemId = getString(record, "id");
  const blob = [
    getString(record, "detail"),
    getString(record, "risk"),
    getString(record, "recommendation"),
  ]
    .join("\n")
    .toLowerCase();

  if (itemId === "security-baseline-posture") {
    if (blob.includes("tool_guard") || blob.includes("dangerous shell")) {
      return "toolGuard";
    }
    if (blob.includes("skill_scanner")) {
      return "skillScanner";
    }
    if (blob.includes("file_guard")) {
      return "fileGuard";
    }
  }

  if (itemId === "enabled-skill-layout") {
    return "skillScanner";
  }

  return null;
}

export function needsManualAction(record: HealthCheckRecord | HealthCheckItem): boolean {
  const status = getString(record, "status");
  return status === "risk" || status === "suggestion";
}
