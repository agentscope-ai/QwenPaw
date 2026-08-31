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
    expect(rule).toMatch(/\.x-markdown li[\s\S]*white-space:\s*normal/);
    expect(rule).toMatch(/overflow-wrap:\s*anywhere/);
    expect(rule).toMatch(/overflow-x:\s*auto/);
    expect(rule).toMatch(/max-width:\s*100%/);
  });

  it("does not preserve structural whitespace between nested list items", () => {
    const marker = '[class*="bubble-start"] .x-markdown li';
    const markerIndex = stylesSource.indexOf(marker);
    const rule = stylesSource.slice(
      markerIndex,
      stylesSource.indexOf("}", markerIndex) + 1,
    );

    expect(markerIndex).toBeGreaterThanOrEqual(0);
    expect(rule).toContain(".x-markdown li");
    expect(rule).toMatch(/white-space:\s*normal/);
    expect(rule).not.toMatch(/white-space:\s*pre-wrap/);
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

describe("Chat mobile layout styles", () => {
  it("releases the vendor chat minimum width on narrow viewports", () => {
    const mobileStart = stylesSource.indexOf(
      "/* The vendor chat layout keeps a 300px minimum width",
    );
    const mobileRule = stylesSource.slice(mobileStart);

    expect(mobileStart).toBeGreaterThanOrEqual(0);
    expect(mobileRule).toContain("@media (max-width: 768px)");
    expect(mobileRule).toContain(".qwenpaw-chat-anywhere-layout");
    expect(mobileRule).toMatch(/min-width:\s*0\s*!important/);
    expect(mobileRule).toContain("safe-area-inset-bottom");
  });

  it("keeps the history panel below the console header", () => {
    const panelStart = stylesSource.indexOf(".historyPanel {");
    const panelRule = stylesSource.slice(
      panelStart,
      stylesSource.indexOf(".suggestionLabel", panelStart),
    );

    expect(panelStart).toBeGreaterThanOrEqual(0);
    expect(panelRule).toMatch(/top:\s*56px/);
  });

  it("keeps the mobile composer toolbar in two stable columns", () => {
    const composerStart = stylesSource.indexOf(
      "/* Mobile composer: keep the input row dominant",
    );
    const composerRule = stylesSource.slice(
      composerStart,
      stylesSource.indexOf("@media (max-width: 480px)", composerStart),
    );

    expect(composerStart).toBeGreaterThanOrEqual(0);
    expect(composerRule).toContain(
      "grid-template-columns: minmax(0, 1fr) auto",
    );
    expect(composerRule).toContain("min-height: 44px");
    expect(composerRule).toContain("min-width: 44px !important");
    expect(composerRule).toContain("flex-wrap: nowrap");
    expect(composerRule).toContain("overflow-x: auto");
    expect(composerRule).toContain("overflow: visible");
  });

  it("removes low-priority composer chrome on narrow phones", () => {
    const narrowStart = stylesSource.indexOf("@media (max-width: 480px)");
    const narrowRule = stylesSource.slice(
      narrowStart,
      stylesSource.indexOf(
        "/* Mobile composer controls share one quiet visual treatment",
        narrowStart,
      ),
    );

    expect(narrowStart).toBeGreaterThanOrEqual(0);
    expect(narrowRule).toContain(".senderContextAffix");
    expect(narrowRule).toMatch(/display:\s*none/);
  });

  it("uses one quiet icon control treatment across the mobile toolbar", () => {
    const toolbarStart = stylesSource.indexOf(
      "/* Mobile composer controls share one quiet visual treatment",
    );
    const toolbarRule = stylesSource.slice(toolbarStart);

    expect(toolbarStart).toBeGreaterThanOrEqual(0);
    expect(toolbarRule).toContain(".mobileComposerControl");
    expect(toolbarRule).toContain("width: 44px !important");
    expect(toolbarRule).toContain("height: 44px !important");
    expect(toolbarRule).toContain("width: 18px");
    expect(toolbarRule).toContain("border: 0 !important");
    expect(toolbarRule).toContain("background: transparent !important");
    expect(toolbarRule).toContain("touch-action: manipulation");
    expect(toolbarRule).toContain('&[aria-expanded="true"]');
    expect(toolbarRule).toContain("&:focus-visible");
    expect(toolbarRule).toContain('&[data-state="running"]');
    expect(toolbarRule).toContain("var(--ant-color-success)");
  });
});
