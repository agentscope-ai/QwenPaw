// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import FilePreview, { getPreviewType, isPreviewable } from "./FilePreview";

describe("FilePreview workspace artifact contract", () => {
  it("recognizes backend preview extensions", () => {
    expect(getPreviewType("image.avif")).toBe("image");
    expect(getPreviewType("notes.markdown")).toBe("markdown");
    expect(getPreviewType("table.tsv")).toBe("csv");
    expect(getPreviewType("script.py")).toBe("text");
    expect(isPreviewable("script.py")).toBe(false);
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
});
