/**
 * themeTokens.test.ts — the <style> projection of plugin token overrides.
 */
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { chatExtensions } from "./registry/chatExtensions";
import { auditStore } from "./registry/audit";
import {
  THEME_TOKEN_STYLE_ID,
  installThemeTokenSync,
  renderThemeTokensCss,
  syncThemeTokens,
} from "./themeTokens";

function styleEl(): HTMLStyleElement | null {
  return document.getElementById(
    THEME_TOKEN_STYLE_ID,
  ) as HTMLStyleElement | null;
}

beforeEach(() => {
  chatExtensions.__resetForTests();
  auditStore.clear();
  styleEl()?.remove();
});

afterEach(() => {
  styleEl()?.remove();
});

describe("renderThemeTokensCss", () => {
  it("returns an empty string when nothing is registered", () => {
    expect(renderThemeTokensCss({})).toBe("");
  });

  it("emits one block per scheme in a fixed order", () => {
    const css = renderThemeTokensCss({
      text: { pluginId: "p1", value: { light: "#111", dark: "#eee" } },
      bg: { pluginId: "p1", value: { light: "#fff", dark: "#000" } },
    });
    expect(css).toBe(
      ":root {\n  --app-bg: #fff;\n  --app-text: #111;\n}\n\n" +
        "html.dark-mode {\n  --app-bg: #000;\n  --app-text: #eee;\n}\n",
    );
  });
});

describe("syncThemeTokens", () => {
  it("creates the style element with both scheme blocks", () => {
    chatExtensions.setThemeTokens("p1", {
      surface: { light: "#fff", dark: "#111" },
    });
    syncThemeTokens();
    const el = styleEl();
    expect(el).not.toBeNull();
    expect(el!.textContent).toContain(":root");
    expect(el!.textContent).toContain("--app-surface: #fff;");
    expect(el!.textContent).toContain("html.dark-mode");
    expect(el!.textContent).toContain("--app-surface: #111;");
  });

  it("reuses the same element when values change", () => {
    syncThemeTokens({
      surface: { pluginId: "p1", value: { light: "#fff", dark: "#111" } },
    });
    const first = styleEl();
    syncThemeTokens({
      surface: { pluginId: "p1", value: { light: "#eee", dark: "#000" } },
    });
    expect(styleEl()).toBe(first);
    expect(styleEl()!.textContent).toContain("--app-surface: #eee;");
  });

  it("removes the element once every override is gone", () => {
    const d = chatExtensions.setThemeTokens("p1", {
      border: { light: "#ccc", dark: "#333" },
    });
    syncThemeTokens();
    expect(styleEl()).not.toBeNull();
    d.dispose();
    syncThemeTokens();
    expect(styleEl()).toBeNull();
  });
});

describe("installThemeTokenSync", () => {
  it("writes on registration, clears on dispose, and unsubscribes", () => {
    const stop = installThemeTokenSync();
    expect(styleEl()).toBeNull();

    const d = chatExtensions.setThemeTokens("p1", {
      text: { light: "#111", dark: "#eee" },
    });
    expect(styleEl()!.textContent).toContain("--app-text: #111;");

    d.dispose();
    expect(styleEl()).toBeNull();

    const again = chatExtensions.setThemeTokens("p2", {
      text: { light: "#222", dark: "#ddd" },
    });
    expect(styleEl()!.textContent).toContain("--app-text: #222;");

    stop();
    expect(styleEl()).toBeNull();
    again.dispose();
    expect(styleEl()).toBeNull();
  });
});
