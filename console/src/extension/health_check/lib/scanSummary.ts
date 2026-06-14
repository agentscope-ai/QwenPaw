import type { HealthCheckItem } from "../api/client";

export type ScanSummary = {
  total: number;
  ok: number;
  risk: number;
  suggestion: number;
  skipped: number;
  attention: number;
};

export function summarizeCheckItems(items: HealthCheckItem[]): ScanSummary {
  let ok = 0;
  let risk = 0;
  let suggestion = 0;
  let skipped = 0;

  for (const item of items) {
    switch (item.status) {
      case "ok":
        ok += 1;
        break;
      case "risk":
        risk += 1;
        break;
      case "suggestion":
        suggestion += 1;
        break;
      case "skipped":
        skipped += 1;
        break;
      default:
        break;
    }
  }

  return {
    total: items.length,
    ok,
    risk,
    suggestion,
    skipped,
    attention: risk + suggestion,
  };
}

export const SESSION_SCAN_STORAGE_KEY = "qwenpaw.healthCheck.lastScan.v1";
