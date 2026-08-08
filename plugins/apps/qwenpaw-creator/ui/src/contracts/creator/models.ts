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
  serper_api_key: string;
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
  tts: ModelConfigItem & {
    voice: string;
    vc_model_name: string;
    reuse_llm_key: boolean;
  };
  s2v: ModelConfigItem & {
    // Free face-detect companion model; empty means the backend default
    // wan2.2-s2v-detect.
    detect_model_name: string;
    reuse_llm_key: boolean;
  };
  image: ModelConfigItem & {
    // Optional in-image text translation model (mode=translate), DashScope
    // provider only; empty means the backend default qwen-mt-image.
    translate_model: string;
  };
  embedding: ModelConfigItem & { reuse_vlm_key: boolean };
  video: ModelConfigItem;
  oss: OssConfig;
  executionAuthorization: {
    mode: "required" | "allow_all";
  };
  creationCheckpoints: {
    mode: "required" | "skip";
  };
  mediaReview: {
    mode: "required" | "auto_approve";
  };
}

export interface ModelConnectionTestRequest {
  type: "llm" | "vlm" | "asr" | "tts" | "s2v" | "embedding" | "image" | "video";
  base_url: string;
  api_key: string;
  model_name: string;
  protocol: string;
  provider?: "whisper" | "fun-asr";
  voice?: string;
}

export interface ConnectionTestResponse {
  ok: boolean;
  ms: number;
  error?: string | null;
  detail?: string | null;
  suggestion?: string | null;
}
