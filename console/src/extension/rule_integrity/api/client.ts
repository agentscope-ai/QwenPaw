import { request } from "@/api/request";

export interface ToolGuardRuleIntegrityFinding {
  file: string;
  reason: string;
  expected_sha256?: string | null;
  actual_sha256?: string | null;
  detail: string;
}

export interface ToolGuardRulesIntegrity {
  type?: "rule_integrity_status" | "connected";
  ok: boolean;
  status: string;
  message: string;
  checked_at?: string | null;
  findings: ToolGuardRuleIntegrityFinding[];
  rules_disabled?: boolean;
  auto_repair_in_progress?: boolean;
  auto_repair_completed?: boolean;
  auto_repair_timeout_retry?: number;
  auto_repair_abandoned?: boolean;
  auto_repair_timeout_max?: number;
  tamper_banner_cycle_active?: boolean;
}

export interface ToolGuardRulesIntegrityRepair {
  ok: boolean;
  message: string;
  source_url: string;
  backup_path?: string | null;
  integrity: ToolGuardRulesIntegrity;
}

export const ruleIntegrityApi = {
  getToolGuardRulesIntegrity: () =>
    request<ToolGuardRulesIntegrity>(
      "/config/security/tool-guard/rules-integrity",
    ),

  repairToolGuardRulesIntegrity: () =>
    request<ToolGuardRulesIntegrityRepair>(
      "/config/security/tool-guard/rules-integrity/repair",
      { method: "POST" },
    ),

  checkIntegrityRuleEntry: () =>
    request<ToolGuardRulesIntegrity>(
      "/config/security/integrity-protection/rules-integrity/check",
      { method: "POST" },
    ),
};
