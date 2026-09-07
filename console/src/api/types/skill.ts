export type SkillSyncStatus =
  | "-"
  | "synced"
  | "outdated"
  | "not_synced"
  | "conflict";

export interface SkillSpec {
  name: string;
  description?: string;
  source: string;
  enabled?: boolean;
  channels?: string[];
  preload?: boolean;
  tags?: string[];
  last_updated?: string;
  emoji?: string;
}

export interface SkillDetail extends SkillSpec {
  content: string;
  config?: Record<string, unknown>;
  installed_from?: string;
}

export interface PoolSkillSpec {
  name: string;
  description?: string;
  source: string;
  external?: boolean;
  external_path?: string;
  sync_status?: SkillSyncStatus | "";
  tags?: string[];
  last_updated?: string;
  emoji?: string;
  auto_sync?: boolean;
  auto_update?: boolean;
}

export interface PoolSkillDetail extends PoolSkillSpec {
  content: string;
  config?: Record<string, unknown>;
  installed_from?: string;
  builtin_language?: string;
  available_builtin_languages?: string[];
  auto_sync_targets?: string[] | null;
}

export interface BuiltinLanguageSpec {
  language: string;
  description?: string;
  version_text?: string;
  source_name?: string;
  status?: "missing" | "current" | "outdated" | "conflict" | string;
}

export interface WorkspaceSkillSummary {
  agent_id: string;
  agent_name?: string;
  skill_names: string[];
}

export interface BuiltinImportSpec {
  name: string;
  description?: string;
  version_text?: string;
  current_version_text?: string;
  current_source?: string;
  current_language?: string;
  available_languages?: string[];
  languages?: Record<string, BuiltinLanguageSpec>;
  status?: "missing" | "current" | "outdated" | "conflict" | string;
}

export interface BuiltinRemovedSpec {
  name: string;
  description?: string;
  current_version_text?: string;
  current_source?: string;
}

export interface BuiltinUpdateNotice {
  fingerprint: string;
  has_updates: boolean;
  total_changes: number;
  actionable_skill_names: string[];
  added: BuiltinImportSpec[];
  missing: BuiltinImportSpec[];
  updated: BuiltinImportSpec[];
  removed: BuiltinRemovedSpec[];
}

export interface PoolAutomationUpdate {
  skill: string;
  language?: string;
  from_version?: string;
  to_version?: string;
  reason?: string;
  detail?: string;
}

export interface PoolAutomationSync {
  skill: string;
  agents?: string[];
}

export interface PoolAutomationResult {
  pool_updated: PoolAutomationUpdate[];
  pool_failed: PoolAutomationUpdate[];
  synced: PoolAutomationSync[];
  sync_failed: PoolAutomationSync[];
  checked: {
    auto_update: number;
    auto_sync: number;
  };
}

export interface SkillAutomationUpdate {
  auto_update?: boolean;
  auto_sync?: {
    enabled: boolean;
    targets?: string[] | null;
  };
}

export interface SkillAutomationResponse {
  updated: boolean;
  auto_update: boolean;
  auto_sync: {
    enabled: boolean;
    targets: string[] | null;
  };
  automation: PoolAutomationResult;
}

export interface HubSkillSpec {
  slug: string;
  name: string;
  description?: string;
  version?: string;
  source_url?: string;
}

export interface HubInstallTaskResponse {
  task_id: string;
  bundle_url: string;
  version: string;
  enable: boolean;
  status: "pending" | "importing" | "completed" | "failed" | "cancelled";
  error: string | null;
  result: {
    installed?: boolean;
    name?: string;
    enabled?: boolean;
    source_url?: string;
    installed_from?: string;
    conflicts?: Array<{
      reason?: string;
      skill_name?: string;
      suggested_name?: string;
    }>;
    [key: string]: unknown;
  } | null;
  created_at: number;
  updated_at: number;
}
