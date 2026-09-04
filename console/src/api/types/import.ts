export type ImportSource = "codex" | "qoder";
export type ImportAssetType = "memory" | "cron" | "skill" | "mcp" | "plugin";
export type ImportAssetState =
  | "pending"
  | "repairing"
  | "ready"
  | "failed"
  | "succeeded"
  | "existing";

export interface ImportSourceProbe {
  source: ImportSource;
  name: string;
  detected: boolean;
}

export interface ImportSelection {
  sessions?: boolean;
  memory?: string[];
  cron?: string[];
  skills?: string[];
  mcp?: string[];
  plugins?: string[];
}

export interface ImportAssetResult {
  asset_type: ImportAssetType;
  source_id: string;
  name: string;
  state: ImportAssetState;
  enabled: boolean | null;
  message: string;
  requires_sessions: boolean;
}

export interface ImportProviderSnapshot {
  source: ImportSource;
  state: string;
  plan_id: string;
  sessions_total: number;
  sessions_processed: number;
  sessions_imported: number;
  selection: ImportSelection;
  assets: ImportAssetResult[];
  error: string;
}

export interface ImportJobSnapshot {
  job_id: string;
  agent_id: string;
  state:
    | "scanning"
    | "awaiting_selection"
    | "running"
    | "cancelling"
    | "completed"
    | "completed_with_issues"
    | "failed"
    | "interrupted";
  seq: number;
  providers: ImportProviderSnapshot[];
  logs: string[];
}

export interface ImportJobEvent {
  seq: number;
  snapshot: ImportJobSnapshot;
}
