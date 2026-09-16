import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const stylesSource = readFileSync(
  join(process.cwd(), "src/pages/SettingsCenter/index.module.less"),
  "utf8",
);

describe("SettingsCenter responsive layout", () => {
  it("lets segmented controls fit their options without trailing space", () => {
    const segmentedStart = stylesSource.indexOf("\n.segmentedControl,") + 1;
    const segmentedRule = stylesSource.slice(
      segmentedStart,
      stylesSource.indexOf("}", segmentedStart) + 1,
    );

    expect(segmentedStart).toBeGreaterThan(0);
    expect(segmentedRule).toContain("width: max-content;");
    expect(segmentedRule).toContain("max-width: 100%;");
    expect(segmentedRule).not.toContain("min-width:");
  });

  it("keeps a Spark-sized narrow-screen content gutter", () => {
    const mobileStart = stylesSource.indexOf("@media (max-width: 768px)");
    const mobileRule = stylesSource.slice(mobileStart);

    expect(mobileStart).toBeGreaterThanOrEqual(0);
    expect(mobileRule).toContain("max-height: 48vh;");
    expect(mobileRule).toContain("padding: 18px 20px;");
    expect(mobileRule).toContain("width: calc(100% - 48px);");
  });

  it("stacks wide controls before the navigation becomes mobile", () => {
    const compactDesktopStart = stylesSource.indexOf(
      "@media (min-width: 769px) and (max-width: 900px)",
    );
    const compactDesktopRule = stylesSource.slice(
      compactDesktopStart,
      stylesSource.indexOf("@media (max-width: 768px)", compactDesktopStart),
    );

    expect(compactDesktopStart).toBeGreaterThanOrEqual(0);
    expect(compactDesktopRule).toContain("flex-wrap: wrap;");
    expect(compactDesktopRule).toContain("width: calc(100% - 48px);");
  });

  it("keeps theme controls compact, aligned and responsive", () => {
    const fieldsStart = stylesSource.indexOf(".themeFields {");
    const fieldsRule = stylesSource.slice(
      fieldsStart,
      stylesSource.indexOf("\n}", fieldsStart) + 2,
    );
    const fieldStart = stylesSource.indexOf(".themeField {");
    const fieldRule = stylesSource.slice(
      fieldStart,
      stylesSource.indexOf(".themePresetField", fieldStart),
    );
    const mobileStart = stylesSource.indexOf("@media (max-width: 768px)");
    const mobileRule = stylesSource.slice(mobileStart);

    expect(fieldsRule).toContain(
      "grid-template-columns: repeat(2, minmax(0, 1fr));",
    );
    expect(fieldsRule).toContain("gap: 18px 20px;");
    expect(fieldRule).toContain("height: 36px;");
    expect(fieldRule).toContain("width: 100%;");
    expect(fieldRule).toContain(
      "box-shadow: 0 0 0 2px var(--app-accent-ring);",
    );
    expect(mobileRule).toContain("grid-template-columns: 1fr;");
    expect(mobileRule).toContain("margin: 18px 0 0;");
  });

  it("uses a compact theme palette swatch", () => {
    const optionStart = stylesSource.indexOf(".themePresetOption {");
    const swatchStart = stylesSource.indexOf(".themePresetSwatch {");
    const optionRule = stylesSource.slice(
      optionStart,
      stylesSource.indexOf("\n}", optionStart) + 2,
    );
    const swatchRule = stylesSource.slice(
      swatchStart,
      stylesSource.indexOf("\n}", swatchStart) + 2,
    );

    expect(optionRule).toContain("gap: 8px;");
    expect(swatchRule).toContain("width: 24px;");
    expect(swatchRule).toContain("height: 24px;");
    expect(swatchRule).toContain("font-size: 13px;");
  });

  it("adapts navigation helpers to dark mode via semantic tokens", () => {
    const navRules = stylesSource.slice(
      stylesSource.indexOf("\n.navItem {"),
      stylesSource.indexOf("\n.noResults {"),
    );
    const backButtonRule = stylesSource.slice(
      stylesSource.indexOf("\n.backButton {"),
      stylesSource.indexOf("\n.searchInput {"),
    );
    const sidebarRule = stylesSource.slice(
      stylesSource.indexOf("\n.sidebar {"),
      stylesSource.indexOf("\n.backButton {"),
    );

    expect(navRules).toContain("color: var(--app-text);");
    expect(navRules).toContain("background: var(--app-fill);");
    expect(navRules).toContain("background: var(--app-nav-selected-bg);");
    expect(backButtonRule).toContain("color: var(--app-text-secondary);");
    expect(sidebarRule).toContain("background: var(--app-shell-bg);");
    expect(sidebarRule).toContain("var(--app-border-subtle)");
  });

  it("keeps the dark override block free of hardcoded colours", () => {
    const darkStart = stylesSource.indexOf(".rootDark {");
    const darkRule = stylesSource.slice(
      darkStart,
      stylesSource.indexOf("\n}", darkStart) + 2,
    );

    expect(darkStart).toBeGreaterThanOrEqual(0);
    expect(darkRule).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
    expect(darkRule).not.toMatch(/rgba?\(/);
  });

  it("keeps general and sidebar controls legible in dark mode", () => {
    const darkStart = stylesSource.indexOf(".rootDark {");
    const darkRule = stylesSource.slice(
      darkStart,
      stylesSource.indexOf("\n}", darkStart) + 2,
    );

    expect(darkRule).toContain(":global(.qwenpaw-segmented-item)");
    expect(darkRule).toContain(":global(.qwenpaw-segmented-item-selected)");
    expect(darkRule).toContain("background: var(--app-fill) !important;");
    expect(darkRule).toContain(":global(.qwenpaw-btn-default)");
    expect(darkRule).toContain(":global(.qwenpaw-btn-text)");
    expect(darkRule).toContain("&:not(:disabled):hover");
    expect(darkRule).toContain("color: var(--app-accent-text);");
    expect(darkRule).toContain("color: var(--app-text-quaternary);");
    expect(darkRule).toContain(":global(.qwenpaw-checkbox-wrapper-disabled)");
    expect(darkRule).toContain("color: var(--app-text);");
  });
});
