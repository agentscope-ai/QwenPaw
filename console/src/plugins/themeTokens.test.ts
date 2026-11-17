/**
 * themeTokens.test.ts — the <style> projection of plugin token overrides.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { chatExtensions } from "./registry/chatExtensions";
import { auditStore } from "./registry/audit";
import { EXTENDED_THEME_TOKENS, ThemeTokens } from "./registry/slotKeys";
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
  it("exposes only roles that tokens.css actually defines", () => {
    // import.meta.url is a vite URL here, so resolve from the console root.
    const css = readFileSync(
      join(process.cwd(), "src", "styles", "tokens.css"),
      "utf8",
    );
    // A typo here would silently no-op at runtime, so pin the names to the
    // stylesheet the console really ships.
    for (const role of Object.values(ThemeTokens)) {
      expect(css).toContain(`--app-${role}:`);
    }
    expect(Object.values(EXTENDED_THEME_TOKENS)).toHaveLength(31);
  });

  it("returns an empty string when nothing is registered", () => {
    expect(renderThemeTokensCss({})).toBe("");
  });

  it("emits one block per scheme in a fixed order", () => {
    const css = renderThemeTokensCss({
      text: { pluginId: "p1", value: { light: "#111", dark: "#eee" } },
      bg: { pluginId: "p1", value: { light: "#fff", dark: "#000" } },
    });
    expect(css).toBe(
      ":root {\n  --app-bg: #fff !important;\n  --app-text: #111 !important;\n}\n\n" +
        "html.dark-mode {\n  --app-bg: #000 !important;\n  --app-text: #eee !important;\n}\n",
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
    expect(el!.textContent).toContain("--app-surface: #fff !important;");
    expect(el!.textContent).toContain("html.dark-mode");
    expect(el!.textContent).toContain("--app-surface: #111 !important;");
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
    expect(styleEl()!.textContent).toContain("--app-surface: #eee !important;");
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

  it("emits the extended semantic roles into their own scheme block", () => {
    chatExtensions.setThemeTokens("p1", {
      "surface-subtle": { light: "#fafafa", dark: "#1a1a1a" },
      "border-strong": { light: "#bbbbbb", dark: "#555555" },
      "accent-hover": { light: "#ff8800", dark: "#ffaa00" },
      "warning-border": { light: "#ff55cc", dark: "#77aa55" },
    });
    syncThemeTokens();
    const css = styleEl()!.textContent ?? "";
    const [rootBlock, darkBlock] = css.split("html.dark-mode");
    expect(rootBlock).toContain("--app-surface-subtle: #fafafa !important;");
    expect(rootBlock).toContain("--app-border-strong: #bbbbbb !important;");
    expect(rootBlock).toContain("--app-accent-hover: #ff8800 !important;");
    expect(rootBlock).toContain("--app-warning-border: #ff55cc !important;");
    expect(darkBlock).toContain("--app-surface-subtle: #1a1a1a !important;");
    expect(darkBlock).toContain("--app-border-strong: #555555 !important;");
    expect(darkBlock).toContain("--app-accent-hover: #ffaa00 !important;");
    expect(darkBlock).toContain("--app-warning-border: #77aa55 !important;");
  });
});

describe("installThemeTokenSync", () => {
  it("writes on registration, clears on dispose, and unsubscribes", () => {
    const stop = installThemeTokenSync();
    expect(styleEl()).toBeNull();

    const d = chatExtensions.setThemeTokens("p1", {
      text: { light: "#111", dark: "#eee" },
    });
    expect(styleEl()!.textContent).toContain("--app-text: #111 !important;");

    d.dispose();
    expect(styleEl()).toBeNull();

    const again = chatExtensions.setThemeTokens("p2", {
      text: { light: "#222", dark: "#ddd" },
    });
    expect(styleEl()!.textContent).toContain("--app-text: #222 !important;");

    stop();
    expect(styleEl()).toBeNull();
    again.dispose();
    expect(styleEl()).toBeNull();
  });
});
