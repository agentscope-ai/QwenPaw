import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const stylesSource = readFileSync(
  join(process.cwd(), "src/styles/layout.css"),
  "utf8",
);

describe("global link accessibility", () => {
  it("keeps a visible keyboard focus indicator on links", () => {
    const focusStart = stylesSource.indexOf("a[href]:focus-visible {");
    const focusRule = stylesSource.slice(
      focusStart,
      stylesSource.indexOf("}", focusStart) + 1,
    );

    expect(focusStart).toBeGreaterThanOrEqual(0);
    expect(focusRule).toContain("outline: 2px solid var(--app-accent);");
    expect(focusRule).toContain("outline-offset: 2px;");
  });
});
