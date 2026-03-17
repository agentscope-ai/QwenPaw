import { describe, expect, it } from "vitest";

import {
  DEFAULT_COUNTRY_CODE,
  FALLBACK_AUTH_META,
  normalizeCountryCode,
  normalizeSupportedCountryCodes,
} from "../../../src/auth/proboost/config";

describe("proboost auth config normalization", () => {
  it("normalizes supported country codes by trimming, deduplicating, and falling back", () => {
    expect(normalizeSupportedCountryCodes([" +86 ", "+1", "+86", " "])).toEqual([
      "+86",
      "+1",
    ]);
    expect(normalizeSupportedCountryCodes([])).toEqual(["+86", "+1", "+81", "+39"]);
  });

  it("prefers a supported input country code and otherwise falls back safely", () => {
    expect(normalizeCountryCode(" +81 ", ["+86", "+81"])).toBe("+81");
    expect(normalizeCountryCode("+44", ["+44", "+86"])).toBe("+44");
    expect(normalizeCountryCode("+44", ["+1", "+39"])).toBe("+1");
    expect(normalizeCountryCode(undefined, ["+1", "+39"])).toBe("+1");
    expect(normalizeCountryCode(undefined)).toBe(DEFAULT_COUNTRY_CODE);
  });

  it("keeps fallback auth metadata consistent with the static fallback list", () => {
    expect(FALLBACK_AUTH_META).toEqual({
      defaultCountryCode: "+86",
      supportedCountryCodes: ["+86", "+1", "+81", "+39"],
      countryCodeOptions: [
        { value: "+86" },
        { value: "+1" },
        { value: "+81" },
        { value: "+39" },
      ],
    });
  });
});

