import type { EmbeddingModelConfig } from "@/api/types/agent";

// Keep in sync with reme_config.py::_OPENAI_COMPAT_EMBEDDING_BACKENDS.
const OPENAI_COMPAT_EMBEDDING_BACKENDS = new Set([
  "openai",
  "dashscope",
  "dashscope_multimodal",
]);

export function isEmbeddingEnabled(config?: Partial<EmbeddingModelConfig>) {
  if (!config?.model_name?.trim()) {
    return false;
  }
  // Mirror reme_config.py::_is_embedding_enabled so the form previews the
  // same capability state that the backend will apply after saving.
  if (OPENAI_COMPAT_EMBEDDING_BACKENDS.has(config.backend || "")) {
    return !!config.api_key?.trim();
  }
  if (config.backend === "gemini") {
    return !!config.api_key?.trim();
  }
  return config.backend === "ollama";
}

export function getEmbeddingServiceFingerprint(
  config?: Partial<EmbeddingModelConfig>,
) {
  if (!config) return "";
  return JSON.stringify([
    config.backend || "",
    config.api_key || "",
    config.base_url?.trim().replace(/\/+$/, "") || "",
    config.model_name?.trim() || "",
    config.dimensions || 0,
    !!config.use_dimensions,
  ]);
}

export function getEmbeddingConfigFingerprint(
  config?: Partial<EmbeddingModelConfig>,
) {
  if (!config) return "";
  return JSON.stringify([
    config.backend || "",
    config.api_key || "",
    config.base_url?.trim().replace(/\/+$/, "") || "",
    config.model_name?.trim() || "",
    config.dimensions || 0,
    !!config.enable_cache,
    !!config.use_dimensions,
    config.max_cache_size || 0,
    config.max_input_length || 0,
    config.max_batch_size || 0,
    config.health_check_timeout || 0,
  ]);
}
