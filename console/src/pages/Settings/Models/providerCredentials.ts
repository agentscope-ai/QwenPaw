import type { ProviderConfigRequest } from "../../../api/types";

const LEGACY_MASK = /^[^*]*\*{3,}$/;

export function buildCredentialUpdate(
  value: string | undefined,
  clear: boolean,
): Pick<ProviderConfigRequest, "api_key" | "clear_api_key"> {
  if (clear) return { clear_api_key: true };
  const normalized = value?.trim();
  if (!normalized || LEGACY_MASK.test(normalized)) return {};
  return { api_key: normalized };
}

export function buildCustomHeadersUpdate(
  headers: Record<string, string>,
  edited: boolean,
): Pick<ProviderConfigRequest, "custom_headers" | "clear_custom_headers"> {
  if (!edited) return {};
  if (Object.keys(headers).length === 0) return { clear_custom_headers: true };
  return { custom_headers: headers };
}

export function buildBaseUrlUpdate(
  value: string | undefined,
  initialValue: string | undefined,
): Pick<ProviderConfigRequest, "base_url" | "clear_base_url"> {
  const normalized = value?.trim() ?? "";
  const initial = initialValue?.trim() ?? "";
  if (normalized === initial) return {};
  if (!normalized) return { clear_base_url: true };
  return { base_url: normalized };
}
