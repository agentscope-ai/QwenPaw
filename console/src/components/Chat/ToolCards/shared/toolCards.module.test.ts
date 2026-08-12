import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const stylesSource = readFileSync(
  join(
    process.cwd(),
    "src/components/Chat/ToolCards/shared/toolCards.module.less",
  ),
  "utf8",
);

function readRule(selector: string): string {
  const selectorIndex = stylesSource.indexOf(`\n${selector} {`) + 1;
  if (selectorIndex === 0) return "";
  return stylesSource.slice(
    selectorIndex,
    stylesSource.indexOf("}", selectorIndex) + 1,
  );
}

describe("Tool card layout styles", () => {
  it.each([
    ".toolCallContainer",
    ".toolCallCompact",
    ".toolCallCompactSummary",
    ".toolCallLabel",
  ])("allows %s to shrink inside a chat message", (selector) => {
    const rule = readRule(selector);

    expect(rule).not.toBe("");
    expect(rule).toMatch(/min-width:\s*0/);
    expect(rule).toMatch(/max-width:\s*100%/);
  });

  it("keeps long tool titles on one ellipsized line", () => {
    const rule = readRule(".toolCallLabel");

    expect(rule).toMatch(/overflow:\s*hidden/);
    expect(rule).toMatch(/text-overflow:\s*ellipsis/);
    expect(rule).toMatch(/white-space:\s*nowrap/);
  });

  it("uses a consistent grid gap for tool metadata panels", () => {
    const rule = readRule(".toolCallMetadata");

    expect(rule).not.toBe("");
    expect(rule).toMatch(/display:\s*grid/);
    expect(rule).toMatch(/gap:\s*6px/);
    expect(rule).toMatch(/min-width:\s*0/);
    expect(rule).toMatch(/max-width:\s*100%/);
  });
});
