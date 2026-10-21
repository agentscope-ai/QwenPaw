import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const tokensSource = readFileSync(
  join(process.cwd(), "src/styles/tokens.css"),
  "utf8",
);

const getRuleDeclarations = (source: string, selector: string) => {
  const ruleStart = source.indexOf(`${selector} {`);
  const declarationsStart = source.indexOf("{", ruleStart) + 1;
  const ruleEnd = source.indexOf("\n}", declarationsStart);

  expect(ruleStart).toBeGreaterThanOrEqual(0);
  expect(ruleEnd).toBeGreaterThan(declarationsStart);

  return source.slice(declarationsStart, ruleEnd).replace(/\s+/g, " ");
};

describe("semantic layout tokens", () => {
  const root = getRuleDeclarations(tokensSource, ":root");

  it("defines the shared spacing and density scales", () => {
    expect(root).toContain("--app-space-1: 4px;");
    expect(root).toContain("--app-space-12: 48px;");
    expect(root).toContain("--app-control-sm: 32px;");
    expect(root).toContain("--app-control-md: 36px;");
    expect(root).toContain("--app-control-lg: 44px;");
    expect(root).toContain("--app-row-compact: 36px;");
    expect(root).toContain("--app-row-default: 44px;");
    expect(root).toContain("--app-row-comfortable: 52px;");
  });

  it("defines responsive hit target and overlay contracts", () => {
    expect(root).toContain("--app-hit-desktop: 32px;");
    expect(root).toContain("--app-hit-touch: 44px;");
    expect(root).toContain("--app-hit-target: var(--app-hit-desktop);");
    expect(root).toContain(
      "--app-overlay-modal-width: min(560px, calc(100vw - 32px));",
    );
    expect(tokensSource).toMatch(
      /@media \(any-pointer: coarse\)[\s\S]*--app-hit-target:\s*var\(--app-hit-touch\)/,
    );
  });
});

describe("semantic interaction tokens", () => {
  const root = getRuleDeclarations(tokensSource, ":root");
  const dark = getRuleDeclarations(tokensSource, "html.dark-mode");

  it("defines motion and focus contracts", () => {
    expect(root).toContain("--app-motion-fast: 120ms;");
    expect(root).toContain("--app-motion-base: 180ms;");
    expect(root).toContain("--app-motion-slow: 240ms;");
    expect(root).toContain("--app-focus-ring-width: 2px;");
    expect(root).toContain("--app-focus-ring-offset: 2px;");
    expect(tokensSource).toMatch(
      /@media \(prefers-reduced-motion: reduce\)[\s\S]*--app-motion-base:\s*1ms/,
    );
  });

  it("defines readable disabled state tokens for both themes", () => {
    for (const declarations of [root, dark]) {
      expect(declarations).toContain("--app-disabled-bg:");
      expect(declarations).toContain("--app-disabled-border:");
      expect(declarations).toContain("--app-disabled-text:");
    }
    expect(root).toContain("--app-disabled-opacity: 0.55;");
  });
});
