export type CheckpointKind = "auto" | "snap" | "pre-restore" | "sha";

export interface CheckpointNode {
  ref: string;
  kind: CheckpointKind;
  session_key: string;
  name: string;
  commit: string;
  sha: string;
  timestamp_ms: number;
  subject: string;
  query: string | null;
  channel: string;
  restore_index: number | null;
  parent_commit: string | null;
  is_head: boolean;
  user_id: string;
  session_id: string;
  session_title: string;
}

export interface CheckpointSession {
  session_key: string;
  session_id: string;
  user_id: string;
  channel: string;
  title: string;
  archived: boolean;
}

export interface CheckpointGraphResponse {
  nodes: CheckpointNode[];
  sessions: CheckpointSession[];
  summary: {
    total: number;
    auto: number;
    snapshots: number;
    safety: number;
    heads: number;
  };
  truncated: boolean;
}

export interface CheckpointStatus {
  auto_enabled: boolean;
  has_checkpoints: boolean;
  workspace_dir: string;
}

export interface RestoreRequest {
  commit: string;
  session_id: string;
  user_id: string;
  channel: string;
  include_memory: boolean;
  include_files: boolean;
  files?: string[];
}

export interface RestoreResult {
  target: string;
  commit: string;
  restored_paths: string[];
  deleted_paths: string[];
  file_paths: string[];
  pre_restore_ref: string | null;
  dry_run: boolean;
  include_memory: boolean;
  include_files: boolean;
}

export interface GcResult {
  deleted_refs: string[];
  kept_refs: string[];
  dry_run: boolean;
}

export interface GcRequest {
  compact?: boolean;
  keep_count?: number;
  keep_days?: number;
  pre_restore_days?: number;
}

export interface CheckpointGcSettings {
  gc_keep_count: number;
  gc_keep_days: number;
  pre_restore_retention_days: number;
}
