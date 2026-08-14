import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const stylesSource = readFileSync(
  join(
    process.cwd(),
    "src/features/files-workspace/FilesWorkspace.module.less",
  ),
  "utf8",
);

describe("Files workspace mobile styles", () => {
  it("stacks navigation and content inside a full-width drawer", () => {
    const marker = "@media (max-width: 768px)";
    const markerIndex = stylesSource.lastIndexOf(marker);
    const rule = stylesSource.slice(markerIndex);

    expect(markerIndex).toBeGreaterThanOrEqual(0);
    expect(rule).toMatch(/width:\s*100%\s*!important/);
    expect(rule).toContain(".workspace:not(.workspaceEmpty)");
    expect(rule).toMatch(/flex-direction:\s*column/);
    expect(rule).toMatch(/grid-template-columns:\s*repeat\(2/);
    expect(rule).toMatch(/min-height:\s*44px/);
    expect(rule).toContain(".sourceTabs button");
    expect(rule).toContain(".treeRow");
    expect(rule).toContain("safe-area-inset-bottom");
  });
});
