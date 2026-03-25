export type KnowledgeSourceType =
  | "file"
  | "directory"
  | "url"
  | "text"
  | "chat";

export interface KnowledgeSourceSpec {
  id: string;
  name: string;
  type: KnowledgeSourceType;
  location: string;
  content: string;
  enabled: boolean;
  recursive: boolean;
  tags: string[];
  summary: string;
}

export interface KnowledgeIndexConfig {
  chunk_size: number;
  chunk_overlap: number;
  max_file_size: number;
  include_globs: string[];
  exclude_globs: string[];
}

export interface KnowledgeAutomationConfig {
  knowledge_auto_collect_chat_files: boolean;
  knowledge_auto_collect_chat_urls: boolean;
  knowledge_auto_collect_long_text: boolean;
  knowledge_long_text_min_chars: number;
}

export interface KnowledgeConfig {
  version: number;
  enabled: boolean;
  sources: KnowledgeSourceSpec[];
  index: KnowledgeIndexConfig;
  automation: KnowledgeAutomationConfig;
}

export interface KnowledgeSourceStatus {
  indexed: boolean;
  indexed_at: string | null;
  document_count: number;
  chunk_count: number;
  error: string | null;
  remote_status?: string;
  remote_cache_state?: string;
  remote_fail_count?: number;
  remote_next_retry_at?: string | null;
  remote_last_error?: string | null;
  remote_updated_at?: string | null;
}

export interface KnowledgeSourceItem extends KnowledgeSourceSpec {
  subject?: string;
  keywords?: string[];
  status: KnowledgeSourceStatus;
}

export interface KnowledgeSourcesResponse {
  enabled: boolean;
  sources: KnowledgeSourceItem[];
}

export interface KnowledgeIndexResult {
  source_id: string;
  document_count: number;
  chunk_count: number;
  indexed_at: string;
}

export interface KnowledgeBulkIndexResult {
  indexed_sources: number;
  results: KnowledgeIndexResult[];
}

export interface KnowledgeSearchHit {
  source_id: string;
  source_name: string;
  source_type: KnowledgeSourceType;
  document_path: string;
  document_title: string;
  score: number;
  snippet: string;
}

export interface KnowledgeSearchResponse {
  query: string;
  hits: KnowledgeSearchHit[];
}

export interface KnowledgeHistoryBackfillStatus {
  has_backfill_record: boolean;
  backfill_completed: boolean;
  marked_unbackfilled: boolean;
  history_chat_count: number;
  has_pending_history: boolean;
  progress?: KnowledgeHistoryBackfillProgress;
}

export interface KnowledgeHistoryBackfillProgress {
  running: boolean;
  completed: boolean;
  failed: boolean;
  total_sessions: number;
  traversed_sessions: number;
  processed_sessions: number;
  current_session_id?: string | null;
  error?: string | null;
  updated_at?: string | null;
  reason?: string | null;
}

export interface KnowledgeHistoryBackfillRunResponse {
  result: {
    changed: boolean;
    skipped: boolean;
    reason?: string;
    processed_sessions?: number;
    file_sources?: number;
    url_sources?: number;
    text_sources?: number;
  };
  status: KnowledgeHistoryBackfillStatus;
}

export interface KnowledgeSourceDocument {
  path: string;
  title: string;
  text: string;
}

export interface KnowledgeSourceContent {
  indexed: boolean;
  indexed_at?: string | null;
  document_count?: number;
  chunk_count?: number;
  documents: KnowledgeSourceDocument[];
}

export interface KnowledgeClearResponse {
  cleared: boolean;
  cleared_indexes: number;
  cleared_sources: number;
  removed_source_configs: boolean;
}

export interface KnowledgeRestoreResponse {
  success: boolean;
  replace_existing: boolean;
  restored_sources: number;
}