import type { ProBoostAuthMeta } from "./types";

export const DEFAULT_COUNTRY_CODE = "+86";

export const SUPPORTED_COUNTRY_CODES = ["+86", "+1", "+81", "+39"] as const;

export function normalizeSupportedCountryCodes(values: readonly string[]): string[] {
  const normalized: string[] = [];

  for (const value of values) {
    const next = value.trim();
    if (next && !normalized.includes(next)) {
      normalized.push(next);
    }
  }

  return normalized.length > 0 ? normalized : [...SUPPORTED_COUNTRY_CODES];
}

export function normalizeCountryCode(
  value: string | undefined,
  supportedCountryCodes: readonly string[] = SUPPORTED_COUNTRY_CODES,
): string {
  const normalizedSupportedCountryCodes = normalizeSupportedCountryCodes(supportedCountryCodes);
  const next = value?.trim();

  if (!next) {
    return normalizedSupportedCountryCodes.includes(DEFAULT_COUNTRY_CODE)
      ? DEFAULT_COUNTRY_CODE
      : normalizedSupportedCountryCodes[0];
  }

  return normalizedSupportedCountryCodes.includes(next)
    ? next
    : normalizedSupportedCountryCodes.includes(DEFAULT_COUNTRY_CODE)
      ? DEFAULT_COUNTRY_CODE
      : normalizedSupportedCountryCodes[0];
}

export const defaultCountryCode = normalizeCountryCode(DEFAULT_COUNTRY_CODE);

export const FALLBACK_AUTH_META: ProBoostAuthMeta = {
  defaultCountryCode,
  supportedCountryCodes: [...SUPPORTED_COUNTRY_CODES],
  countryCodeOptions: SUPPORTED_COUNTRY_CODES.map((value) => ({ value })),
};


