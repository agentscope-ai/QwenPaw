import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useTimezoneOptions } from "./useTimezoneOptions";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    i18n: {
      resolvedLanguage: "en",
      language: "en",
    },
  }),
}));

describe("useTimezoneOptions", () => {
  it("returns an array of TimezoneOption objects with value and label string properties", () => {
    const { result } = renderHook(() => useTimezoneOptions());
    const options = result.current;

    expect(Array.isArray(options)).toBe(true);
    for (const option of options) {
      expect(typeof option.value).toBe("string");
      expect(typeof option.label).toBe("string");
    }
  });

  it("returns a non-empty array containing at least UTC and Asia/Shanghai", () => {
    const { result } = renderHook(() => useTimezoneOptions());
    const options = result.current;

    expect(options.length).toBeGreaterThan(0);

    const values = options.map((o) => o.value);
    expect(values).toContain("UTC");
    expect(values).toContain("Asia/Shanghai");
  });

  it("returns non-empty label strings when locale is en", () => {
    const { result } = renderHook(() => useTimezoneOptions());
    const options = result.current;

    for (const option of options) {
      expect(option.label.length).toBeGreaterThan(0);
    }
  });

  it("is memoized — same array reference across re-renders with the same locale", () => {
    const { result, rerender } = renderHook(() => useTimezoneOptions());
    const first = result.current;
    rerender();
    const second = result.current;

    expect(first).toBe(second);
  });
});
