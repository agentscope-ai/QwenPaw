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

  it("preserves multiline output without spacing normal markdown blocks", () => {
    const marker = "Fix #6852";
    const markerIndex = stylesSource.indexOf(marker);
    const rule = stylesSource.slice(
      markerIndex,
      stylesSource.indexOf("/* End #6852 */", markerIndex),
    );

    expect(markerIndex).toBeGreaterThanOrEqual(0);
    expect(rule).toContain('[class*="markdown"]:not(.x-markdown)');
    expect(rule).toContain(".x-markdown p");
    expect(rule).toContain(".x-markdown li");
    expect(rule).toMatch(/white-space:\s*pre-wrap/);
    expect(rule).toMatch(/overflow-wrap:\s*anywhere/);
    expect(rule).toMatch(/overflow-x:\s*auto/);
    expect(rule).toMatch(/max-width:\s*100%/);
  });
});

describe("Chat attachment preview styles", () => {
  it("wraps attachment cards within a bounded scrollable preview", () => {
    const marker = "Fix #6583";
    const markerIndex = stylesSource.indexOf(marker);
    const rule = stylesSource.slice(
      markerIndex,
      stylesSource.indexOf("/* End #6583 */", markerIndex),
    );

    expect(markerIndex).toBeGreaterThanOrEqual(0);
    expect(rule).toContain(".qwenpaw-sender-header");
    expect(rule).toContain(".qwenpaw-attachment-list");
    expect(rule).toMatch(/flex-wrap:\s*wrap/);
    expect(rule).toMatch(/max-height:\s*\d+px/);
    expect(rule).toMatch(/overflow-y:\s*auto/);
    expect(rule).toMatch(/overflow-x:\s*hidden/);
    expect(rule).not.toContain(".qwenpaw-attachment-list-card-type-overview");
    expect(rule).toMatch(/@media\s*\(max-width:\s*600px\)/);
    expect(rule).toMatch(/column-gap:\s*8px/);
    expect(rule).toMatch(/padding-inline:\s*6px/);
  });
});
