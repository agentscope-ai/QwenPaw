export interface ModelInfo {
  id: string;
  name: string;
}

export interface ProviderInfo {
  id: string;
  name: string;
  api_key_prefix: string;
  chat_model: string;
  /** Built-in models (for built-in providers) or all models (for custom). */
  models: ModelInfo[];
  /** User-added models (deletable). Only populated for built-in providers. */
  extra_models: ModelInfo[];
  is_custom: boolean;
  is_local: boolean;
  /** True when the base_url should be frozen (not editable). */
  freeze_url: boolean;
  /** True when an API key is required for this provider. */
  require_api_key: boolean;
  api_key: string;
  base_url: string;
  generate_kwargs: Record<string, unknown>;
}

export interface ProviderConfigRequest {
  api_key?: string;
  base_url?: string;
  chat_model?: string;
  generate_kwargs?: Record<string, unknown>;
}

export interface ModelSlotConfig {
  provider_id: string;
  model: string;
}

export interface ActiveModelsInfo {
  active_llm?: ModelSlotConfig;
}

export interface ModelSlotRequest {
  provider_id: string;
  model: string;
}

/* ---- Custom provider CRUD ---- */

export interface CreateCustomProviderRequest {
  id: string;
  name: string;
  default_base_url?: string;
  api_key_prefix?: string;
  chat_model?: string;
  models?: ModelInfo[];
}

export interface AddModelRequest {
  id: string;
  name: string;
}

/* ---- Local models ---- */

export interface LocalModelResponse {
  id: string;
  repo_id: string;
  filename: string;
  backend: string;
  source: string;
  file_size: number;
  local_path: string;
  display_name: string;
}

export interface DownloadModelRequest {
  repo_id: string;
  filename?: string;
  backend: string;
  source: string;
}

export interface DownloadTaskResponse {
  task_id: string;
  status: "pending" | "downloading" | "completed" | "failed" | "cancelled";
  repo_id: string;
  filename: string | null;
  backend: string;
  source: string;
  error: string | null;
  result: LocalModelResponse | null;
}

/* ---- Ollama models ---- */

export interface OllamaModelResponse {
  name: string;
  size: number;
  digest?: string | null;
  modified_at?: string | null;
}

export interface OllamaDownloadRequest {
  name: string;
}

export interface OllamaDownloadTaskResponse {
  task_id: string;
  status: "pending" | "downloading" | "completed" | "failed" | "cancelled";
  name: string;
  error: string | null;
  result: OllamaModelResponse | null;
}

/* ---- Test Connection ---- */

export interface TestConnectionResponse {
  success: boolean;
  message: string;
}

export interface TestProviderRequest {
  api_key?: string;
  base_url?: string;
  chat_model?: string;
  generate_kwargs?: Record<string, unknown>;
}

export interface TestModelRequest {
  model_id: string;
}

export interface DiscoverModelsResponse {
  success: boolean;
  message: string;
  models: ModelInfo[];
  added_count: number;
}
