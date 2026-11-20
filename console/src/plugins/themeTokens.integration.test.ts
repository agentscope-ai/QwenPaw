/**
 * Integration: plugin theme tokens vs. the user's preset.
 *
 * App.tsx applies the user's preset as *inline* custom properties on <html>
 * (`--app-surface`, `--app-accent`, …). Inline declarations outrank plain
 * stylesheet rules, so before this fix every preset silently beat the plugin
 * layer on all six presets. These tests drive the real registry + projection
 * and assert the *computed* value on the document element, which is what the
 * user actually sees — not the text of the emitted stylesheet.
 *
 * Flow covered: preset applied → plugin registers tokens → light/dark flip →
 * preset changes while the plugin is active → plugin logs out (dispose) and
 * the preset comes back untouched.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { chatExtensions } from "./registry/chatExtensions";
import { auditStore } from "./registry/audit";
import { THEME_TOKEN_STYLE_ID, installThemeTokenSync } from "./themeTokens";

const root = () => document.documentElement;

/** Mirrors the inline writes App.tsx makes for the active preset. */
function applyPreset(values: Record<string, string>): void {
  for (const [name, value] of Object.entries(values)) {
    root().style.setProperty(`--app-${name}`, value);
  }
}

function computed(token: string): string {
  return getComputedStyle(root()).getPropertyValue(`--app-${token}`).trim();
}

function styleEl(): HTMLStyleElement | null {
  return document.getElementById(
    THEME_TOKEN_STYLE_ID,
  ) as HTMLStyleElement | null;
}

beforeEach(() => {
  chatExtensions.__resetForTests();
  auditStore.clear();
  styleEl()?.remove();
  root().className = "";
  root().removeAttribute("style");
});

afterEach(() => {
  styleEl()?.remove();
  root().className = "";
  root().removeAttribute("style");
});

describe("plugin theme tokens override the user preset", () => {
  it("wins over the preset's inline --app-surface in both schemes", () => {
    // 1. The user is on a preset: App.tsx writes it inline on <html>.
    applyPreset({ surface: "#ffffff" });
    expect(computed("surface")).toBe("#ffffff");

    // 2. Startup hook + a plugin registering its tokens.
    const uninstall = installThemeTokenSync();
    const registration = chatExtensions.setThemeTokens("demo-theme", {
      surface: { light: "#123456", dark: "#0a0a0a" },
      bg: { light: "#fefefe", dark: "#050505" },
    });

    // 3. Light: the plugin wins even though the preset is inline.
    expect(root().style.getPropertyValue("--app-surface")).toBe("#ffffff");
    expect(computed("surface")).toBe("#123456");
    expect(computed("bg")).toBe("#fefefe");

    // 4. Dark: same, from the html.dark-mode block.
    root().classList.add("dark-mode");
    expect(computed("surface")).toBe("#0a0a0a");
    expect(computed("bg")).toBe("#050505");

    // 5. Switching preset while the plugin is active must not leak through.
    applyPreset({ surface: "#eeeeee" });
    expect(root().style.getPropertyValue("--app-surface")).toBe("#eeeeee");
    expect(computed("surface")).toBe("#0a0a0a");

    // 6. Logout: disposing the last override removes the stylesheet and the
    //    user's current preset (as last written) applies again, untouched.
    registration.dispose();
    expect(styleEl()).toBeNull();
    expect(computed("surface")).toBe("#eeeeee");
    expect(computed("bg")).toBe("");

    // 7. Back to light: still the preset, no residue from the plugin.
    root().classList.remove("dark-mode");
    expect(computed("surface")).toBe("#eeeeee");

    uninstall();
    expect(styleEl()).toBeNull();
  });

  it("restores the preset when the plugin is unloaded (logout path)", () => {
    applyPreset({ surface: "#ffffff" });
    root().classList.add("dark-mode");
    applyPreset({ surface: "#101010" });
    expect(computed("surface")).toBe("#101010");

    const uninstall = installThemeTokenSync();
    chatExtensions.setThemeTokens("demo-theme", {
      surface: { light: "#123456", dark: "#0a0a0a" },
    });
    expect(computed("surface")).toBe("#0a0a0a");

    // Runtime teardown disposes every registration the plugin owns.
    chatExtensions.disposeAll("demo-theme");
    expect(styleEl()).toBeNull();
    expect(computed("surface")).toBe("#101010");

    root().classList.remove("dark-mode");
    expect(computed("surface")).toBe("#101010");
    uninstall();
  });

  it("keeps the preset intact when two plugins take turns", () => {
    applyPreset({ surface: "#ffffff" });
    const uninstall = installThemeTokenSync();

    const first = chatExtensions.setThemeTokens("theme-a", {
      surface: { light: "#111111", dark: "#999999" },
    });
    expect(computed("surface")).toBe("#111111");

    const second = chatExtensions.setThemeTokens("theme-b", {
      surface: { light: "#222222", dark: "#888888" },
    });
    expect(computed("surface")).toBe("#222222");

    // LIFO: removing the newer one falls back to the older registration.
    second.dispose();
    expect(computed("surface")).toBe("#111111");

    // Removing the last one restores the preset exactly as it was.
    first.dispose();
    expect(computed("surface")).toBe("#ffffff");
    expect(root().style.getPropertyValue("--app-surface")).toBe("#ffffff");

    uninstall();
  });
});
