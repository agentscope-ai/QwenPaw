import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import FilePreview, { getPreviewType, isPreviewable } from "./FilePreview";

describe("FilePreview", () => {
  it("recognizes artifact preview extensions", () => {
    expect(getPreviewType("image.avif")).toBe("image");
    expect(getPreviewType("notes.markdown")).toBe("markdown");
    expect(getPreviewType("table.tsv")).toBe("csv");
    expect(getPreviewType("script.py")).toBe("text");
    expect(isPreviewable("script.py")).toBe(true);
  });

  it("renders explicitly declared text previews", () => {
    render(
      <FilePreview
        filePath="report.txt"
        content="artifact content"
        previewKind="text"
      />,
    );

    expect(screen.getByText("artifact content")).toBeInTheDocument();
  });

  it("uses tabs as delimiters for TSV previews", () => {
    render(
      <FilePreview
        filePath="report.tsv"
        content={"name\tvalue\nA\t1"}
        previewKind="csv"
      />,
    );

    expect(screen.getByRole("columnheader", { name: "name" })).toBeVisible();
    expect(screen.getByRole("cell", { name: "1" })).toBeVisible();
  });

  it("shows YAML frontmatter as metadata while preserving the body", () => {
    render(
      <FilePreview
        filePath="memory-search.md"
        content={[
          "---",
          "description: Memory Search query guidance",
          "name: memory-search-query-best-practices",
          "---",
          "",
          "## When to Use",
          "",
          "Use this when searching memory.",
        ].join("\n")}
      />,
    );

    const frontmatter = within(screen.getByLabelText("Front matter"));
    expect(frontmatter.getByText("description")).toBeInTheDocument();
    expect(
      frontmatter.getByText("Memory Search query guidance"),
    ).toBeInTheDocument();
    expect(frontmatter.getByText("name")).toBeInTheDocument();
    expect(
      frontmatter.getByText("memory-search-query-best-practices"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: "When to Use" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Use this when searching memory."),
    ).toBeInTheDocument();
  });
});
