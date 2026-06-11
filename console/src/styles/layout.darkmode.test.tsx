/**
 * Dark-mode token application tests for layout.css / aionui-tokens.less.
 *
 * Goal: assert that the CSS source files contain the correct dark-mode
 * overrides for .qwenpaw-bubble-list-wrapper and .qwenpaw-chat-anywhere-input
 * so they use var(--bg-1) rather than a hardcoded #fff in dark mode.
 *
 * We test the CSS *source text* directly because jsdom does not support
 * stylesheet cascade (injected <style> rules do not affect getComputedStyle),
 * making source inspection the reliable approach for this class of test.
 */

import { describe, it, expect } from "vitest";
import { readFileSync } from "fs";
import path from "path";

const LAYOUT_CSS_PATH = path.resolve(
  __dirname,
  "layout.css",
);

const layoutCss = readFileSync(LAYOUT_CSS_PATH, "utf-8");

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Returns true if `css` contains a dark-mode selector block for `classSelector`
 * that sets `property` to a CSS variable (var(...)) rather than a hardcoded value.
 *
 * Handles comma-separated selectors on multiple lines.
 */
function hasDarkOverrideWithToken(
  css: string,
  classSelector: string,
  property: string,
): boolean {
  // Split into rule blocks: each ends at '}'
  const blocks = css.split("}");
  for (const block of blocks) {
    const selectorPart = block.split("{")[0] ?? "";
    const bodyPart = block.split("{")[1] ?? "";
    // The selector part must contain both 'html.dark-mode' and the classSelector
    if (
      selectorPart.includes("html.dark-mode") &&
      selectorPart.includes(classSelector)
    ) {
      // The body must contain the property set to var(...)
      const propPattern = new RegExp(
        `${property}\\s*:\\s*var\\(`,
        "i",
      );
      if (propPattern.test(bodyPart)) return true;
    }
  }
  return false;
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("layout.css dark-mode token application", () => {

  it("dark-mode scope contains a background rule for .qwenpaw-bubble-list-wrapper", () => {
    // There must be an 'html.dark-mode .qwenpaw-bubble-list-wrapper' rule
    expect(layoutCss).toMatch(/html\.dark-mode[\s\S]*?\.qwenpaw-bubble-list-wrapper/);
  });

  it("dark-mode scope contains a background rule for .qwenpaw-chat-anywhere-input", () => {
    expect(layoutCss).toMatch(/html\.dark-mode[\s\S]*?\.qwenpaw-chat-anywhere-input/);
  });

  it(".qwenpaw-bubble-list-wrapper dark-mode background uses a CSS variable (not hardcoded #fff)", () => {
    const usesToken = hasDarkOverrideWithToken(
      layoutCss,
      ".qwenpaw-bubble-list-wrapper",
      "background",
    );
    expect(
      usesToken,
      "Expected html.dark-mode .qwenpaw-bubble-list-wrapper to use var(--bg-*) not #fff",
    ).toBe(true);
  });

  it(".qwenpaw-chat-anywhere-input dark-mode background uses a CSS variable (not hardcoded #fff)", () => {
    const usesToken = hasDarkOverrideWithToken(
      layoutCss,
      ".qwenpaw-chat-anywhere-input",
      "background",
    );
    expect(
      usesToken,
      "Expected html.dark-mode .qwenpaw-chat-anywhere-input to use var(--bg-*) not #fff",
    ).toBe(true);
  });

  it("light-mode .qwenpaw-bubble-list-wrapper rule exists (regression guard)", () => {
    // The bare-class rule must also be present (the light-mode default)
    expect(layoutCss).toMatch(/\.qwenpaw-bubble-list-wrapper\s*\{/);
  });

  it("light-mode .qwenpaw-chat-anywhere-input rule exists (regression guard)", () => {
    expect(layoutCss).toMatch(/\.qwenpaw-chat-anywhere-input\s*\{/);
  });

  it("dark-mode --bg-1 token is defined in layout.css", () => {
    // The dark token block must define --bg-1
    expect(layoutCss).toMatch(/html\.dark-mode[\s\S]*?--bg-1\s*:/);
  });
});
