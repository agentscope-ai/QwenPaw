/**
 * API-key validation rules for the provider configuration modal.
 *
 * Extracted from ProviderConfigModal.tsx so the validation contract can be
 * unit-tested without rendering the modal. Behaviour is unchanged.
 *
 * Regressions guarded here:
 * - #79: the validation condition and its error message were written
 *   backwards, so a correct key was rejected while a wrong-prefix key was
 *   accepted. The contract (asserted by tests):
 *     * a key that does NOT start with any allowed prefix is invalid;
 *     * a key matching one of the allowed prefixes is valid;
 *     * empty values, providers without prefix rules, and auth_token mode
 *       are never rejected.
 */

export interface ApiKeyPrefixSource {
  api_key_prefix?: string;
  api_key_prefixes?: string[];
}

/**
 * Resolves the allowed key prefixes for a provider.
 * The list form wins; falls back to the single prefix; empty when neither.
 */
export function getValidApiKeyPrefixes(provider: ApiKeyPrefixSource): string[] {
  if (provider.api_key_prefixes && provider.api_key_prefixes.length > 0) {
    return provider.api_key_prefixes;
  }
  if (provider.api_key_prefix) {
    return [provider.api_key_prefix];
  }
  return [];
}

/**
 * Validates an API key value against the allowed prefixes.
 * Returns an error message key-context when invalid, or null when the value
 * is acceptable.
 *
 * Rules:
 * - empty/missing values pass (keeping an existing key unchanged);
 * - without prefix constraints every non-empty value passes;
 * - auth_token mode bypasses prefix checks (Anthropic auth tokens have no
 *   `sk-`-style prefix);
 * - otherwise the value must start with at least one allowed prefix.
 */
export function validateApiKey(
  value: string | undefined,
  prefixes: string[],
  authMode: "api_key" | "auth_token",
): { valid: true } | { valid: false; prefix: string } {
  if (
    value &&
    prefixes.length > 0 &&
    authMode !== "auth_token" &&
    !prefixes.some((prefix) => value.startsWith(prefix))
  ) {
    return { valid: false, prefix: prefixes.join(", ") };
  }
  return { valid: true };
}
