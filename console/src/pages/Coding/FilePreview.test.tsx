import { render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import FilePreview, { getPreviewType, isPreviewable } from "./FilePreview";

const previewUrl = vi.hoisted(() => vi.fn());

vi.mock("../../api/modules/workspace", () => ({
  workspaceApi: {
    getArtifactPreviewUrl: previewUrl,
    getFileDownloadUrl: vi.fn(),
  },
}));

vi.mock("../../api/authHeaders", () => ({
  buildAuthHeaders: () => ({ Authorization: "Bearer test-token" }),
}));

vi.mock("../../utils/openExternalLink", () => ({
  isDesktopTauriRuntime: () => false,
}));

describe("FilePreview", () => {
  afterEach(() => {
    previewUrl.mockReset();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("pins binary previews to the historical artifact root", async () => {
    previewUrl.mockReturnValue(
      "/api/agents/analyst/workspace/artifact-previews/report.png?root=project&root_ref=project-a",
    );
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        headers: new Headers({ "Content-Length": "4" }),
        blob: async () => new Blob(["image"]),
      }),
    );
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:preview");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);

    render(
      <FilePreview
        content=""
        filePath="report.png"
        artifactLocator={{
          agentId: "analyst",
          chatId: "chat-1",
          path: "report.png",
          root: "project",
          rootRef: "project-a",
        }}
        previewKind="image"
        artifactSize={5}
      />,
    );

    await waitFor(() => {
      expect(previewUrl).toHaveBeenCalledWith({
        agentId: "analyst",
        chatId: "chat-1",
        path: "report.png",
        root: "project",
        rootRef: "project-a",
      });
      expect(fetch).toHaveBeenCalledWith(
        "/api/agents/analyst/workspace/artifact-previews/report.png?root=project&root_ref=project-a",
        expect.objectContaining({
          headers: {
            Authorization: "Bearer test-token",
            "X-Chat-Id": "chat-1",
          },
        }),
      );
    });
  });

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
