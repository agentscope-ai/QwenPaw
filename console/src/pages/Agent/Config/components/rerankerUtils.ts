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
 * the backend uses (reranker_history.py::_canonical_timeout) so a fractional
 * timeout such as 1.5 yields an identical digest on both sides.
 */
function canonicalTimeout(timeout: unknown): string {
  const value = typeof timeout === "number" ? timeout : Number(timeout || 0);
  const text = Number.isFinite(value)
    ? value.toFixed(6).replace(/0+$/, "").replace(/\.$/, "")
    : "0";
  return text || "0";
}

/**
 * SHA-256 digest of the normalized service configuration, kept in sync with
 * reranker_history.py::service_fingerprint. The raw API key never leaves
 * this digest, so the fingerprint is safe to put in query strings and the
 * history file.
 */
export async function getRerankerServiceFingerprint(
  config?: Partial<RerankerConfig>,
): Promise<string> {
  if (!config) return "";
  const canonical = JSON.stringify([
    config.base_url?.trim().replace(/\/+$/, "") || "",
    config.api_key || "",
    config.model_name?.trim() || "",
    canonicalTimeout(config.timeout),
  ]);
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(canonical),
  );
  const hex = Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
  return `sha256:${hex}`;
}
