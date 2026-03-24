export interface AgentRequest {
  input: unknown;
  session_id?: string | null;
  user_id?: string | null;
  channel?: string | null;
  [key: string]: unknown;
}

export interface LocalEmbeddingConfig {
  enabled: boolean;
  model_id: string;
  model_path: string | null;
  device: string;
  dtype: "fp16" | "bf16" | "fp32";
  download_source: "modelscope" | "huggingface";
}

export interface EmbeddingModelInfo {
  id: string;
  type: "multimodal" | "text";
  dimensions: number;
  pooling: string;
  mrl_enabled?: boolean;
  mrl_min_dims?: number;
}

export interface EmbeddingPresetModels {
  multimodal: EmbeddingModelInfo[];
  text: EmbeddingModelInfo[];
}

export interface EmbeddingTestResult {
  success: boolean;
  message: string;
  latency_ms?: number;
  model_info?: Record<string, unknown>;
}

export interface ModelDownloadStatus {
  status: "downloading" | "completed" | "error";
  progress?: number;
  message: string;
  local_path?: string;
}

export interface AgentsRunningConfig {
  max_iters: number;
  llm_retry_enabled: boolean;
  llm_max_retries: number;
  llm_backoff_base: number;
  llm_backoff_cap: number;
  max_input_length: number;
  memory_compact_ratio: number;
  memory_reserve_ratio: number;
  tool_result_compact_recent_n: number;
  tool_result_compact_old_threshold: number;
  tool_result_compact_recent_threshold: number;
  tool_result_compact_retention_days: number;
  local_embedding: LocalEmbeddingConfig;
}
