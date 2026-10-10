import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const stylesSource = readFileSync(
  join(process.cwd(), "src/styles/layout.css"),
  "utf8",
);
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

  return source
    .slice(declarationsStart, ruleEnd)
    .replace(/\/\*[\s\S]*?\*\//g, "");
};

describe("global link accessibility", () => {
  it("keeps a visible keyboard focus indicator on links", () => {
    const focusStart = stylesSource.indexOf("a[href]:focus-visible {");
    const focusRule = stylesSource.slice(
      focusStart,
      stylesSource.indexOf("}", focusStart) + 1,
    );

    expect(focusStart).toBeGreaterThanOrEqual(0);
    expect(focusRule).toContain("outline: 2px solid var(--app-focus-ring);");
    expect(focusRule).toContain("outline-offset: 2px;");
  });

  it("defines contrast-safe focus rings in the correct theme scopes", () => {
    const lightTheme = getRuleDeclarations(tokensSource, ":root");
    const darkTheme = getRuleDeclarations(tokensSource, "html.dark-mode");

    expect(lightTheme).toContain("--app-focus-ring: var(--app-accent-text);");
    expect(darkTheme).toContain("--app-focus-ring: var(--app-accent-text);");
  });
});
