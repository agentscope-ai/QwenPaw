import { describe, expect, it } from "vitest";
import { isValidElement } from "react";
import type { ReactElement, ReactNode } from "react";

import { renderMarkdown, splitCompletionMarker } from "./markdown";

function tags(nodes: ReactNode[]): string[] {
  return nodes
    .filter((node): node is ReactElement => isValidElement(node))
    .map((node) => String(node.type));
}

function textOf(node: ReactNode): string {
  if (node === null || node === undefined || typeof node === "boolean") {
    return "";
  }
  if (typeof node === "string" || typeof node === "number") {
    return String(node);
  }
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (isValidElement(node)) {
    return textOf((node.props as { children?: ReactNode }).children);
  }
  return "";
}

describe("renderMarkdown", () => {
  it("renders GFM tables as table elements", () => {
    const nodes = renderMarkdown(
      [
        "| Date | GAAP |",
        "|------|------|",
        "| 2026-03-01 | 4.64 |",
        "| 2026-03-02 | 4.04 |",
      ].join("\n"),
    );
    expect(tags(nodes)).toEqual(["table"]);
    expect(textOf(nodes)).toContain("2026-03-02");
    expect(textOf(nodes)).toContain("GAAP");
  });

  it("renders headings, paragraphs, and lists", () => {
    const nodes = renderMarkdown(
      "## Summary\n\nPlain text.\n\n- first\n- second",
    );
    expect(tags(nodes)).toEqual(["h2", "p", "ul"]);
  });

  it("renders bold and inline code within a paragraph", () => {
    const nodes = renderMarkdown("**Month**: `March 2026`");
    expect(tags(nodes)).toEqual(["p"]);
    expect(textOf(nodes)).toBe("Month: March 2026");
  });

  it("keeps fenced code verbatim", () => {
    const nodes = renderMarkdown("```sql\nSELECT * FROM t\n```");
    expect(tags(nodes)).toEqual(["pre"]);
    expect(textOf(nodes)).toBe("SELECT * FROM t");
  });

  it("never emits raw markup for angle brackets", () => {
    const nodes = renderMarkdown("<img src=x onerror=alert(1)>");
    expect(textOf(nodes)).toBe("<img src=x onerror=alert(1)>");
    expect(tags(nodes)).toEqual(["p"]);
  });

  // Regression: every input below previously stalled the parser or could
  // stall it — the outer loop must consume at least one line per pass.
  it("terminates on a hash line that is not a heading", () => {
    const nodes = renderMarkdown("#not-a-heading");
    expect(tags(nodes)).toEqual(["p"]);
    expect(textOf(nodes)).toBe("#not-a-heading");
  });

  it("terminates on consecutive special-prefix non-block lines", () => {
    const nodes = renderMarkdown("#tag-one\n#tag-two\n>quoted-no-space");
    expect(tags(nodes)).toEqual(["p", "p", "p"]);
    expect(textOf(nodes)).toContain("quoted-no-space");
  });

  it("renders five and six hash headings at the smallest level", () => {
    const nodes = renderMarkdown("##### five\n\n###### six");
    expect(tags(nodes)).toEqual(["h4", "h4"]);
    expect(textOf(nodes)).toBe("fivesix");
  });

  it("terminates on an unclosed fenced code block", () => {
    const nodes = renderMarkdown("```sql\nSELECT 1");
    expect(tags(nodes)).toEqual(["pre"]);
    expect(textOf(nodes)).toBe("SELECT 1");
  });

  it("terminates on mixed ordered and unordered list runs", () => {
    const nodes = renderMarkdown("1. first\n- second\n2. third");
    expect(tags(nodes)).toEqual(["ol"]);
    expect(textOf(nodes)).toBe("firstsecondthird");
  });

  it("terminates on a lone table-like row without a separator", () => {
    const nodes = renderMarkdown("| a | b |");
    expect(tags(nodes)).toEqual(["p"]);
    expect(textOf(nodes)).toBe("| a | b |");
  });
});

describe("splitCompletionMarker", () => {
  it("splits a trailing marker off the body", () => {
    const { body, marker } = splitCompletionMarker(
      "Result text.\n\n〚 analysis | completed: done 〛",
    );
    expect(body).toBe("Result text.");
    expect(marker).toBe("analysis | completed: done");
  });

  it("returns the text untouched when no marker exists", () => {
    const { body, marker } = splitCompletionMarker("Just text.");
    expect(body).toBe("Just text.");
    expect(marker).toBe("");
  });
});
