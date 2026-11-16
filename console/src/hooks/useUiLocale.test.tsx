import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import type { Locale } from "antd/es/locale";
import dayjs from "dayjs";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

beforeEach(() => {
  vi.resetModules();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  dayjs.locale("en");
});

describe("UI locale loading", () => {
  it.each([
    ["zh-CN", "zh-cn"],
    ["ja-JP", "ja"],
    ["ru_RU", "ru"],
    ["ID-id", "id"],
    ["en-US", "en"],
    ["pt-BR", "en"],
  ])(
    "loads %s without importing other languages",
    async (language, expected) => {
      const { loadUiLocale, uiLocaleLoaders } = await import("./useUiLocale");
      const spies = Object.entries(uiLocaleLoaders).map(([key]) =>
        vi.spyOn(uiLocaleLoaders, key as keyof typeof uiLocaleLoaders),
      );
      expect((await loadUiLocale(language)).locale).toBe(expected);
      expect(
        spies.reduce((count, spy) => count + spy.mock.calls.length, 0),
      ).toBe(1);
    },
  );

  it("caches shared region variants and retries after a failed load", async () => {
    const { loadUiLocale, uiLocaleLoaders } = await import("./useUiLocale");
    const loader = vi
      .spyOn(uiLocaleLoaders, "zh")
      .mockRejectedValueOnce(new Error("offline"));
    await expect(loadUiLocale("zh-CN")).rejects.toThrow("offline");
    const retry = loadUiLocale("zh-CN");
    expect(loadUiLocale("zh-TW")).toBe(retry);
    expect((await retry).locale).toBe("zh-cn");
    expect(loader).toHaveBeenCalledTimes(2);
  });

  it("applies the initial regional locale to antd and dayjs", async () => {
    const { useUiLocale } = await import("./useUiLocale");
    const { result } = renderHook(() => useUiLocale("zh-CN"));
    await waitFor(() => expect(result.current.locale).toBe("zh-cn"));
    expect(dayjs.locale()).toBe("zh-cn");
    expect(dayjs().subtract(1, "day").fromNow()).toContain("前");
  });

  it("ignores stale locale completion after a rapid language switch", async () => {
    const { useUiLocale, uiLocaleLoaders } = await import("./useUiLocale");
    let finishChinese!: (locale: Locale) => void;
    vi.spyOn(uiLocaleLoaders, "zh").mockReturnValueOnce(
      new Promise<Locale>((resolve) => {
        finishChinese = resolve;
      }),
    );
    const { result, rerender } = renderHook(
      ({ language }) => useUiLocale(language),
      { initialProps: { language: "zh-CN" } },
    );
    rerender({ language: "ja-JP" });
    await waitFor(() => expect(result.current.locale).toBe("ja"));
    await act(async () => {
      finishChinese({ locale: "zh-cn" });
    });
    expect(result.current.locale).toBe("ja");
    expect(dayjs.locale()).toBe("ja");
  });

  it("falls back visibly to English and permits retry after failure", async () => {
    const { useUiLocale, uiLocaleLoaders } = await import("./useUiLocale");
    vi.spyOn(uiLocaleLoaders, "zh").mockRejectedValueOnce(new Error("offline"));
    const error = vi
      .spyOn(console, "error")
      .mockImplementation(() => undefined);
    const { result, rerender } = renderHook(
      ({ language }) => useUiLocale(language),
      { initialProps: { language: "zh" } },
    );
    await waitFor(() => expect(error).toHaveBeenCalledTimes(1));
    expect(result.current.locale).toBe("en");
    expect(dayjs.locale()).toBe("en");
    rerender({ language: "en" });
    rerender({ language: "zh" });
    await waitFor(() => expect(result.current.locale).toBe("zh-cn"));
  });

  it("does not update global locale after unmount", async () => {
    const { useUiLocale, uiLocaleLoaders } = await import("./useUiLocale");
    let finish!: (locale: Locale) => void;
    vi.spyOn(uiLocaleLoaders, "ru").mockReturnValueOnce(
      new Promise<Locale>((resolve) => {
        finish = resolve;
      }),
    );
    const { unmount } = renderHook(() => useUiLocale("ru"));
    unmount();
    await act(async () => {
      finish({ locale: "ru" });
    });
    expect(dayjs.locale()).toBe("en");
  });
});
