export interface AgentRequest {
  input: unknown;
  session_id?: string | null;
  user_id?: string | null;
  channel?: string | null;
  [key: string]: unknown;
}

export type EmbeddingBackendType = "openai" | "transformers" | "ollama";

/** Canonical embedding block (matches Python ``EmbeddingConfig``). */
export interface EmbeddingConfigShape {
  enabled: boolean;
  backend_type: EmbeddingBackendType;
  backend?: string;
  api_key?: string;
  base_url?: string;
  model_name?: string;
  dimensions?: number;
  enable_cache?: boolean;
  use_dimensions?: boolean;
  max_cache_size?: number;
  max_input_length?: number;
  max_batch_size?: number;
  model_id: string;
  model_path: string | null;
  device: string;
  dtype: "fp16" | "bf16" | "fp32";
  download_source: "modelscope" | "huggingface";
}

/** Response shape for ``/config/agents/local-embedding`` (transformers slice). */
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

/** Response from ``/config/agents/embedding/resource-hint`` */
export interface EmbeddingGpuInfo {
  index: number;
  name: string;
  total_memory_mb: number | null;
  source?: string;
}

export interface EmbeddingResourceHint {
  platform: string;
  cpu_count: number | null;
  ram_total_gb: number | null;
  ram_available_gb: number | null;
  gpus: EmbeddingGpuInfo[];
  recommendation: string;
  model_tiers: {
    text_small: string;
    text_mid: string;
    multimodal_2b: string;
  };
  note: string;
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
  history_max_length?: number;
  embedding_config: EmbeddingConfigShape;
}
