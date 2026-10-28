import type { RerankerConfig } from "@/api/types/agent";

// Keep in sync with reme_reranker.py::load_reranker_config: the backend only
// treats reranking as active when the switch is on and a model is set, and
// call_reranker_api additionally needs a base URL to post to.
export function isRerankerConfigured(config?: Partial<RerankerConfig>) {
  return Boolean(
    config?.enabled &&
      config?.base_url?.trim() &&
      config?.model_name?.trim(),
  );
}

export function getRerankerServiceFingerprint(
  config?: Partial<RerankerConfig>,
) {
  if (!config) return "";
  return JSON.stringify([
    config.base_url?.trim().replace(/\/+$/, "") || "",
    config.api_key || "",
    config.model_name?.trim() || "",
    config.timeout || 0,
  ]);
}
