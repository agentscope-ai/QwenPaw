import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const stylesSource = readFileSync(
  join(process.cwd(), "src/pages/Chat/index.module.less"),
  "utf8",
);

describe("Chat message markdown layout styles", () => {
  it("wraps long lines for assistant markdown fallback content", () => {
    const marker = "Fix #5480";
    const markerIndex = stylesSource.indexOf(marker);
    const rule = stylesSource.slice(
      markerIndex,
      stylesSource.indexOf("}", markerIndex) + 1,
    );

    expect(markerIndex).toBeGreaterThanOrEqual(0);
    expect(rule).toContain('[class*="bubble-start"] [class*="markdown"]');
    expect(rule).not.toMatch(/white-space:\s*pre-wrap/);
    expect(rule).toMatch(/overflow-wrap:\s*anywhere/);
    expect(rule).toMatch(/word-break:\s*normal/);
    expect(rule).toMatch(/min-width:\s*0/);
    expect(rule).toMatch(/max-width:\s*100%/);
  });
});
