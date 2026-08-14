import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const stylesSource = readFileSync(
  join(process.cwd(), "src/layouts/index.module.less"),
  "utf8",
);
const componentSource = readFileSync(
  join(process.cwd(), "src/layouts/Sidebar.tsx"),
  "utf8",
);

describe("Sidebar mobile layout", () => {
  it("keeps the expanded sidebar and footer inside the visual viewport", () => {
    const marker = "@media (max-width: 768px)";
    const markerIndex = stylesSource.lastIndexOf(marker);
    const rule = stylesSource.slice(markerIndex);

    expect(markerIndex).toBeGreaterThanOrEqual(0);
    expect(rule).toContain(".siderMobileExpanded");
    expect(rule).toMatch(/position:\s*fixed\s*!important/);
    expect(rule).toContain("calc(100dvh - 56px)");
    expect(rule).toContain("safe-area-inset-bottom");
    expect(rule).toMatch(/\.collapseToggle\s*{[^}]*min-width:\s*44px/s);
    expect(rule).toMatch(/\.collapseToggle\s*{[^}]*min-height:\s*44px/s);
  });

  it("renders a dismissible backdrop and accessible collapse control", () => {
    expect(componentSource).toContain("styles.mobileSidebarBackdrop");
    expect(componentSource).toContain('aria-controls="app-sidebar"');
    expect(componentSource).toContain("aria-expanded={!collapsed}");
    expect(componentSource).toContain('event.key === "Escape"');
  });
});
