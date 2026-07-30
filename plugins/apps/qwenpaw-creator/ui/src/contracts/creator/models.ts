export interface ModelConfigItem {
  enabled: boolean;
  model_name: string;
  api_key: string;
  base_url: string;
  protocol: string;
  custom_protocol: string;
}

export interface OssConfig {
  enabled: boolean;
  access_key_id: string;
  access_key_secret: string;
  endpoint: string;
  bucket: string;
  public_base_url: string;
  policy_api_key: string;
}

export interface GroundingConfig extends ModelConfigItem {
  reuse_llm: boolean;
  validation_source: "llm" | "vlm" | "custom";
  tavily_api_key: string;
  native_search_enabled: boolean;
  search_provider: "dashscope_qwen";
  search_reuse_llm: boolean;
  search_model_name: string;
  search_api_key: string;
  search_base_url: string;
  search_protocol: string;
}

export interface ModelConfigData {
  llm: ModelConfigItem & { multimodal: boolean };
  vlm: ModelConfigItem & { use_llm: boolean; multimodal: boolean };
  grounding: GroundingConfig;
  asr: ModelConfigItem & {
    provider: "whisper" | "fun-asr";
    language: string;
    reuse_llm_key: boolean;
  };
  image: ModelConfigItem;
  video: ModelConfigItem;
  oss: OssConfig;
  executionAuthorization: {
    mode: "required" | "allow_all";
  };
}

export interface ModelConnectionTestRequest {
  type: "llm" | "vlm" | "asr" | "image" | "video";
  base_url: string;
  api_key: string;
  model_name: string;
  protocol: string;
  provider?: "whisper" | "fun-asr";
}

export interface ConnectionTestResponse {
  ok: boolean;
  ms: number;
  error?: string | null;
  detail?: string | null;
  suggestion?: string | null;
}
