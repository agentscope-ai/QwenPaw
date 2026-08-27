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
    spy.mockRestore();
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
