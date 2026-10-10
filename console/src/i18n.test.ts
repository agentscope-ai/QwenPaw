import { afterEach, describe, expect, it, vi } from "vitest";

// ---------------------------------------------------------------------------
// i18n initial language — regression for #1604
// (language setting was lost after restart: the app initialized back to
// English instead of restoring the persisted language).
// The write side (LanguageSwitcher → localStorage) is covered by
// LanguageSwitcher.test.tsx; this covers the READ side at startup.
//
// i18n reads `localStorage("language") || navigator.language || "en"` at
// module load, so each case re-imports the module fresh.
// ---------------------------------------------------------------------------

async function freshI18n() {
  vi.resetModules();
  const mod = await import("./i18n");
  return mod.default;
}

async function freshI18nModule() {
  vi.resetModules();
  return import("./i18n");
}

describe("i18n initial language (#1604)", () => {
  afterEach(() => {
    localStorage.clear();
    vi.resetModules();
  });

  it("restores the persisted language from localStorage on startup", async () => {
    localStorage.setItem("language", "zh");

    const i18n = await freshI18n();
    if (!i18n.isInitialized) {
      await new Promise((resolve) => i18n.on("initialized", resolve));
    }

    expect(i18n.language).toBe("zh");
    expect(i18n.t("common.loading")).toBe("加载中...");
  });

  it("falls back to navigator.language when nothing is persisted", async () => {
    const spy = vi.spyOn(navigator, "language", "get").mockReturnValue("ja-JP");

    const i18n = await freshI18n();
    if (!i18n.isInitialized) {
      await new Promise((resolve) => i18n.on("initialized", resolve));
    }

    // ja-JP resolves into the Japanese bundle (nonExplicitSupportedLngs)
    expect(i18n.language).toBe("ja-JP");
    expect(i18n.language.startsWith("ja")).toBe(true);
    expect(i18n.t("common.loading")).toBe("読み込み中...");
    spy.mockRestore();
  });

  it("loads a new locale when the language changes", async () => {
    const i18n = await freshI18n();
    if (!i18n.isInitialized) {
      await new Promise((resolve) => i18n.on("initialized", resolve));
    }

    await i18n.changeLanguage("pt-BR");

    expect(i18n.t("common.loading")).toBe("Carregando...");
  });

  it("retries a locale after its first load fails", async () => {
    const mod = await freshI18nModule();
    const loader = vi
      .spyOn(mod.localeLoaders, "zh")
      .mockRejectedValueOnce(new Error("network error"))
      .mockResolvedValueOnce({ common: { loading: "加载中..." } });

    await expect(mod.loadLocale("zh")).rejects.toThrow("network error");
    await expect(mod.loadLocale("zh")).resolves.toEqual({
      common: { loading: "加载中..." },
    });
    expect(loader).toHaveBeenCalledTimes(2);
  });

  it("logs and falls back to English when a locale fails to load", async () => {
    const mod = await freshI18nModule();
    const error = new Error("network error");
    vi.spyOn(mod.localeLoaders, "zh").mockRejectedValueOnce(error);
    const consoleError = vi
      .spyOn(console, "error")
      .mockImplementation(() => undefined);

    const i18n = mod.default;
    if (!i18n.isInitialized) {
      await new Promise((resolve) => i18n.on("initialized", resolve));
    }
    await i18n.changeLanguage("zh");

    expect(consoleError).toHaveBeenCalledWith(
      'Failed to load locale "zh", falling back:',
      error,
    );
    expect(i18n.t("common.loading")).toBe("Loading...");
  });

  it("uses the initialized instance for built-in menu labels", async () => {
    localStorage.setItem("language", "zh");

    const i18n = await freshI18n();
    if (!i18n.isInitialized) {
      await new Promise((resolve) => i18n.on("initialized", resolve));
    }

    const { BUILTIN_MENU } = await import("./layouts/registry/builtinMenu");
    const inbox = BUILTIN_MENU.find((item) => item.id === "core.inbox");

    expect(typeof inbox?.label).toBe("function");
    expect(typeof inbox?.label === "function" ? inbox.label() : null).toBe(
      "收件箱",
    );
  });

  it("defaults to en when neither localStorage nor navigator gives a language", async () => {
    const spy = vi.spyOn(navigator, "language", "get").mockReturnValue("xx-XX");

    const i18n = await freshI18n();
    if (!i18n.isInitialized) {
      await new Promise((resolve) => i18n.on("initialized", resolve));
    }

    expect(i18n.language).toBe("en");
    spy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// pt-BR bundle resolution — regression for the language list fix.
// nonExplicitSupportedLngs reduces a region-qualified code to its
// language part before matching supportedLngs, so "pt-BR" was looked
// up as "pt", rejected, and the UI silently fell back to English.
// Asserting only i18n.language cannot catch this: it stayed "pt-BR"
// while resolvedLanguage degraded to "en".
// ---------------------------------------------------------------------------

describe("i18n pt-BR bundle resolution", () => {
  afterEach(() => {
    localStorage.clear();
    vi.resetModules();
  });

  it("resolves a persisted pt-BR on startup", async () => {
    localStorage.setItem("language", "pt-BR");

    const i18n = await freshI18n();
    if (!i18n.isInitialized) {
      await new Promise((resolve) => i18n.on("initialized", resolve));
    }

    expect(i18n.resolvedLanguage).toBe("pt-BR");
    expect(i18n.t("chat.newTask")).toBe("Nova tarefa");
  });

  it("resolves pt-BR after an explicit switch", async () => {
    const i18n = await freshI18n();
    if (!i18n.isInitialized) {
      await new Promise((resolve) => i18n.on("initialized", resolve));
    }

    await i18n.changeLanguage("pt-BR");

    expect(i18n.resolvedLanguage).toBe("pt-BR");
    expect(i18n.t("chat.newTask")).toBe("Nova tarefa");
  });
});
