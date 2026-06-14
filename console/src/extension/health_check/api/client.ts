import { request } from "@/api/request";

export interface HealthCheckItem {
  [key: string]: unknown;
  group: string;
  id: string;
  label?: string;
  status: string;
  detail: string;
  risk: string;
  recommendation: string;
  fix_id?: string | null;
  deep_only: boolean;
}

export interface HealthCheckRepairSuggestion {
  label: string;
  doctor_fix_id: string;
  requires_confirmation: boolean;
}

export interface HealthCheckScanResponse {
  scan_id: string;
  read_only: boolean;
  progress: number;
  check_items: HealthCheckItem[];
  risk_summary: string[];
  repair_suggestions: HealthCheckRepairSuggestion[];
  mutated_files: string[];
}

export interface HealthCheckFixResponse {
  confirmed: boolean;
  selected_repair: string;
  fix_id: string;
  executed: boolean;
  exit_code: number;
  output: string[];
}

export const healthCheckApi = {
  runIntegrityHealthCheckScan: (deep: boolean = false) =>
    request<HealthCheckScanResponse>(
      "/config/security/integrity-protection/health-check/scan",
      {
        method: "POST",
        body: JSON.stringify({ deep }),
      },
    ),

  runIntegrityHealthCheckFix: (fixId: string) =>
    request<HealthCheckFixResponse>(
      "/config/security/integrity-protection/health-check/fix",
      {
        method: "POST",
        body: JSON.stringify({
          fix_id: fixId,
          selected_repair: `repair_${fixId}`,
        }),
      },
    ),
};
