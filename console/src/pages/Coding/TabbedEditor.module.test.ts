import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const stylesSource = readFileSync(
  join(process.cwd(), "src/pages/Coding/TabbedEditor.module.less"),
  "utf8",
);

describe("Tabbed editor mobile open-files styles", () => {
  it("keeps the open-files panel within the viewport", () => {
    const marker = "@container (max-width: 520px)";
    const markerIndex = stylesSource.indexOf(marker);
    const rule = stylesSource.slice(
      markerIndex,
      stylesSource.indexOf(".iconBtn", markerIndex),
    );

    expect(markerIndex).toBeGreaterThanOrEqual(0);
    expect(rule).toMatch(/\.tabBar\s*{[^}]*height:\s*46px/s);
    expect(rule).toMatch(/\.openFilesBtn\s*{[^}]*height:\s*44px/s);
    expect(rule).toMatch(/width:\s*calc\(100% - 8px\)/);
    expect(rule).toContain("100dvh");
    expect(rule).toMatch(/min-height:\s*44px/);
    expect(rule).toMatch(/font-size:\s*16px/);
    expect(rule).toContain("safe-area-inset-bottom");
  });
});
