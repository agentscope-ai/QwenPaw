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

  it("keeps navigation helpers legible in dark mode", () => {
    const darkStart = stylesSource.indexOf(".rootDark {");
    const darkRule = stylesSource.slice(
      darkStart,
      stylesSource.indexOf("\n}", darkStart) + 2,
    );

    expect(darkStart).toBeGreaterThanOrEqual(0);
    expect(darkRule).toContain(".backButton");
    expect(darkRule).toContain(".settingsAgentSelect");
    expect(darkRule).toContain(".navItem {");
    expect(darkRule).toContain("color: rgba(255, 255, 255, 0.75);");
    expect(darkRule).toContain("rgba(255, 255, 255, 0.12)");
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
