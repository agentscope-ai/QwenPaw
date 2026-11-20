import type { RerankerConfig } from "@/api/types/agent";

// Keep in sync with reme_reranker.py::load_reranker_config: the backend only
// treats reranking as active when the switch is on and a model is set, and
// call_reranker_api additionally needs a base URL to post to.
export function isRerankerConfigured(config?: Partial<RerankerConfig>) {
  return Boolean(
    config?.enabled && config?.base_url?.trim() && config?.model_name?.trim(),
  );
}

/**
 * Normalize a timeout to the same six-decimal, trailing-zero-stripped text
 * the backend uses (reranker_history.py::_canonical_timeout).
 */
function canonicalTimeout(timeout: unknown): string {
  const value = typeof timeout === "number" ? timeout : Number(timeout || 0);
  const text = Number.isFinite(value)
    ? value.toFixed(6).replace(/0+$/, "").replace(/\.$/, "")
    : "0";
  return text || "0";
}

/**
 * Stable in-memory identity for a reranker configuration.
 *
 * Used only to decide whether a stored manual verdict still describes the
 * form's current settings. It is never sent to the server and never hashed:
 * history lookup is computed server-side from the saved agent configuration,
 * because `crypto.subtle` is unavailable on a plain-HTTP console served from
 * a non-loopback origin.
 */
export function getRerankerConfigKey(config?: Partial<RerankerConfig>): string {
  if (!config) return "";
  return JSON.stringify([
    config.base_url?.trim().replace(/\/+$/, "") || "",
    config.api_key || "",
    config.model_name?.trim() || "",
    canonicalTimeout(config.timeout),
  ]);
}
