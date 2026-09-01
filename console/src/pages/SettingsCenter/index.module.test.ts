import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const stylesSource = readFileSync(
  join(process.cwd(), "src/pages/SettingsCenter/index.module.less"),
  "utf8",
);

describe("SettingsCenter responsive layout", () => {
  it("lets segmented controls fit their options without trailing space", () => {
    const segmentedStart = stylesSource.indexOf(".segmentedControl,");
    const segmentedRule = stylesSource.slice(
      segmentedStart,
      stylesSource.indexOf("}", segmentedStart) + 1,
    );

    expect(segmentedStart).toBeGreaterThanOrEqual(0);
    expect(segmentedRule).toContain("width: max-content;");
    expect(segmentedRule).toContain("max-width: 100%;");
    expect(segmentedRule).not.toContain("min-width:");
  });

  it("keeps a Spark-sized narrow-screen content gutter", () => {
    const mobileStart = stylesSource.indexOf("@media (max-width: 768px)");
    const mobileRule = stylesSource.slice(mobileStart);

    expect(mobileStart).toBeGreaterThanOrEqual(0);
    expect(mobileRule).toContain("padding: 18px 20px;");
    expect(mobileRule).toContain("width: calc(100% - 48px);");
  });
});
