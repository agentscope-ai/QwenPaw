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

type Rgb = readonly [number, number, number];

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

const mix = (foreground: Rgb, background: Rgb, weight: number): Rgb => [
  foreground[0] * weight + background[0] * (1 - weight),
  foreground[1] * weight + background[1] * (1 - weight),
  foreground[2] * weight + background[2] * (1 - weight),
];

const linearize = (channel: number) => {
  const value = channel / 255;

  return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
};

const luminance = (color: Rgb) =>
  0.2126 * linearize(color[0]) +
  0.7152 * linearize(color[1]) +
  0.0722 * linearize(color[2]);

const contrast = (foreground: Rgb, background: Rgb) => {
  const lighter = Math.max(luminance(foreground), luminance(background));
  const darker = Math.min(luminance(foreground), luminance(background));

  return (lighter + 0.05) / (darker + 0.05);
};

describe("global link accessibility", () => {
  it("keeps a visible keyboard focus indicator on links", () => {
    const focusStart = stylesSource.indexOf("a[href]:focus-visible {");
    const focusRule = stylesSource.slice(
      focusStart,
      stylesSource.indexOf("}", focusStart) + 1,
    );

    expect(focusStart).toBeGreaterThanOrEqual(0);
    expect(focusRule).toContain(
      "outline: var(--app-focus-ring-width) solid var(--app-focus-ring);",
    );
    expect(focusRule).toContain(
      "outline-offset: var(--app-focus-ring-offset);",
    );
  });

  it("defines contrast-safe focus rings in the correct theme scopes", () => {
    const lightTheme = getRuleDeclarations(tokensSource, ":root");
    const darkTheme = getRuleDeclarations(tokensSource, "html.dark-mode");

    expect(lightTheme).toContain("--app-focus-ring: var(--app-accent-text);");
    expect(darkTheme).toContain("--app-focus-ring: var(--app-accent-text);");
  });

  it("keeps selected navigation text readable in both theme scopes", () => {
    const lightTheme = getRuleDeclarations(tokensSource, ":root");
    const darkTheme = getRuleDeclarations(tokensSource, "html.dark-mode");
    const compactLightTheme = lightTheme.replace(/\s+/g, " ");

    expect(compactLightTheme).toContain(
      "--app-nav-selected-text: color-mix(in srgb, " +
        "var(--app-accent) 65%, black);",
    );
    expect(darkTheme).toContain(
      "--app-nav-selected-text: var(--app-accent-text);",
    );

    const accent: Rgb = [255, 127, 22];
    const accentHover: Rgb = [255, 157, 77];
    const shell: Rgb = [249, 248, 244];
    const black: Rgb = [0, 0, 0];
    const selectedText = mix(accent, black, 0.65);
    const selectedBackground = mix(accent, shell, 0.1);
    const hoverBackground = mix(accentHover, shell, 0.16);

    expect(contrast(selectedText, selectedBackground)).toBeGreaterThanOrEqual(
      4.5,
    );
    expect(contrast(selectedText, hoverBackground)).toBeGreaterThanOrEqual(4.5);
  });
});
