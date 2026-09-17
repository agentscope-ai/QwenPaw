import { render, screen, within, waitFor, act } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import FilePreview, { getPreviewType, isPreviewable } from "./FilePreview";

describe("FilePreview", () => {
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

// ---------------------------------------------------------------------------
// getPreviewType / isPreviewable — regression for #5863
// (Coding session images were not displayed because image files did not
// enable preview mode; the file-type decision must be covered by tests)
// ---------------------------------------------------------------------------
describe("getPreviewType (#5863)", () => {
  it.each([
    ["photo.png", "image"],
    ["photo.jpg", "image"],
    ["photo.JPEG", "image"], // case-insensitive extension
    ["anim.gif", "image"],
    ["pic.webp", "image"],
    ["icon.svg", "image"],
    ["favicon.ico", "image"],
    ["bitmap.bmp", "image"],
  ])("detects image type for %s", (path, expected) => {
    expect(getPreviewType(path)).toBe(expected);
  });

  it("detects pdf / markdown / html / csv types", () => {
    expect(getPreviewType("doc.pdf")).toBe("pdf");
    expect(getPreviewType("README.md")).toBe("markdown");
    expect(getPreviewType("notes.mdx")).toBe("markdown");
    expect(getPreviewType("page.html")).toBe("html");
    expect(getPreviewType("page.htm")).toBe("html");
    expect(getPreviewType("data.csv")).toBe("csv");
  });

  it("returns none for unknown or extensionless paths", () => {
    expect(getPreviewType("script.py")).toBe("none");
    expect(getPreviewType("archive.zip")).toBe("none");
    expect(getPreviewType("Makefile")).toBe("none");
  });

  it("uses only the last extension segment", () => {
    // "notes.md.bak" must NOT be treated as markdown
    expect(getPreviewType("notes.md.bak")).toBe("none");
    expect(getPreviewType("photo.png.tmp")).toBe("none");
  });
});

describe("isPreviewable (#5863)", () => {
  it("returns true for previewable types and false for others", () => {
    expect(isPreviewable("photo.png")).toBe(true);
    expect(isPreviewable("README.md")).toBe(true);
    expect(isPreviewable("script.py")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Image preview rendering — regression for A#82584296 (image preview not working)
// When a file has an image extension, FilePreview must render an <img>
// element (after blob loading) rather than falling through to null.
// ---------------------------------------------------------------------------

// Mock dependencies for image preview tests
vi.mock("@/stores/agentStore", () => ({
  useAgentStore: vi.fn((selector?: (s: any) => any) =>
    selector
      ? selector({ selectedAgent: "default" })
      : { selectedAgent: "default" },
  ),
}));
vi.mock("@/api/authHeaders", () => ({
  buildAuthHeaders: () => ({}),
}));
vi.mock("@/api/modules/workspace", () => ({
  workspaceApi: {
    getFileDownloadUrl: (path: string) => `/api/files/${path}`,
    loadFileChunk: vi.fn(),
  },
}));

describe("FilePreview image rendering (A#82584296)", () => {
  const mockBlobUrl = "blob:http://localhost/fake-blob-id";
  let fetchSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      blob: () =>
        Promise.resolve(new Blob(["fake-image-data"], { type: "image/png" })),
    });
    global.fetch = fetchSpy as unknown as typeof fetch;
    vi.spyOn(URL, "createObjectURL").mockReturnValue(mockBlobUrl);
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
  });

  it("renders an <img> element for PNG files after loading", async () => {
    await act(async () => {
      render(<FilePreview filePath="screenshot.png" content="" />);
    });

    await waitFor(() => {
      const img = screen.getByRole("img");
      expect(img).toBeInTheDocument();
      expect(img.getAttribute("src")).toBe(mockBlobUrl);
    });
  });

  it("sets alt text from the filename", async () => {
    await act(async () => {
      render(<FilePreview filePath="photos/vacation.jpg" content="" />);
    });

    await waitFor(() => {
      const img = screen.getByRole("img");
      expect(img.getAttribute("alt")).toBe("vacation.jpg");
    });
  });

  it("shows error state when blob fetch fails", async () => {
    fetchSpy.mockResolvedValue({
      ok: false,
      status: 404,
    });

    await act(async () => {
      render(<FilePreview filePath="missing.png" content="" />);
    });

    // After fetch fails, should not render an <img>
    await waitFor(() => {
      expect(screen.queryByRole("img")).not.toBeInTheDocument();
    });
  });
});
