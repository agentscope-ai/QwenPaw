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
