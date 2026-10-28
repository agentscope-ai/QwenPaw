import {
  render,
  screen,
  within,
  waitFor,
  act,
  fireEvent,
} from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import FilePreview, { getPreviewType, isPreviewable } from "./FilePreview";
import { openHtmlFile } from "../../utils/openHtmlFile";

vi.mock("../../utils/openHtmlFile", () => ({
  openHtmlFile: vi.fn(),
}));

describe("FilePreview", () => {
  it.each([
    '"memory_tags": [Orion, Vega]',
    "'memory_tags': [Orion, Vega]",
    "defaults: &defaults\n  memory_tags: [Orion, Vega]\n<<: *defaults",
    "memory_tags: [Old]\nmemory_tags: [Orion, Vega]",
  ])("renders one clickable tag row from resolved YAML: %s", (frontmatter) => {
    const onTagClick = vi.fn();
    render(
      <FilePreview
        filePath="memory.md"
        content={`---\n${frontmatter}\n---\nBody`}
        onMemoryTagClick={onTagClick}
      />,
    );
    const tags = screen.getAllByRole("button");
    expect(tags.map((tag) => tag.textContent)).toEqual(["Orion", "Vega"]);
    fireEvent.click(tags[0]);
    expect(onTagClick).toHaveBeenCalledExactlyOnceWith("Orion");
  });
  it("renders individual tags and sends the clicked tag to the workspace", () => {
    const onTagClick = vi.fn();
    render(
      <FilePreview
        filePath="memory.md"
        content={'---\nmemory_tags: ["赵六", "Orion"]\n---\n# Memory'}
        onMemoryTagClick={onTagClick}
      />,
    );
    const tag = screen.getByText("Orion");
    expect(tag.tagName).toBe("BUTTON");
    fireEvent.click(tag);
    expect(onTagClick).toHaveBeenCalledExactlyOnceWith("Orion");
    expect(screen.getByRole("heading", { name: "Memory" })).toBeInTheDocument();
  });

  it("keeps tags readable without a memory navigation context", () => {
    render(
      <FilePreview
        filePath="attachment.md"
        content={"---\nmemory_tags: [Orion]\n---\nText"}
      />,
    );
    expect(screen.getByText("Orion").tagName).toBe("SPAN");
  });

  it("shows memory tags written as a YAML block list", () => {
    render(
      <FilePreview
        filePath="memory.md"
        content={
          "---\nmemory_tags:\n- 赵六\n- 上海示例科技有限公司\n---\n# Memory"
        }
      />,
    );
    const frontmatter = screen.getByLabelText("Front matter");
    expect(frontmatter).toHaveTextContent("赵六");
    expect(frontmatter).toHaveTextContent("上海示例科技有限公司");
  });

  it("keeps math code blocks in the renderable code block controls", () => {
    render(
      <FilePreview
        filePath="formula.md"
        content={["```math", "x^2 + y^2 = z^2", "```"].join("\n")}
      />,
    );

    const tabs = screen.getAllByRole("tab", { hidden: true });
    expect(tabs).toHaveLength(2);
    expect(screen.getByLabelText("common.copy")).toBeInTheDocument();
    expect(screen.getByLabelText("common.download")).toBeInTheDocument();

    (tabs[1] as HTMLButtonElement).click();
    expect(screen.getByRole("tabpanel", { hidden: true })).toHaveTextContent(
      "x^2 + y^2 = z^2",
    );
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

describe("FilePreview read-only HTML", () => {
  const dynamicContent = [
    "<!doctype html>",
    '<html><head><meta charset="utf-8">',
    "<style>body { background: #05070f; }</style>",
    '</head><body><div id="root"></div>',
    '<script>document.body.appendChild(document.createElement("canvas"));</script>',
    "</body></html>",
  ].join("\n");

  it.each(["scene.html", "scene.htm"])(
    "shows browser guidance instead of a blank script-generated %s",
    (filePath) => {
      render(<FilePreview filePath={filePath} content={dynamicContent} />);

      expect(screen.queryByTitle("files.htmlPreview")).not.toBeInTheDocument();
      expect(screen.getByRole("status")).toHaveTextContent(
        "files.htmlReadOnlyNotice",
      );
      expect(
        screen.getByRole("button", { name: "files.openHtmlInBrowser" }),
      ).toBeInTheDocument();
    },
  );

  it("opens the original HTML with its workspace context from the fallback", () => {
    const options = {
      filePath: "scene.html",
      content: dynamicContent,
      chatId: "chat-1",
      projectDirOverride: "/project",
      root: "workspace" as const,
      workspaceBacked: true,
    };
    render(<FilePreview {...options} />);

    fireEvent.click(
      screen.getByRole("button", { name: "files.openHtmlInBrowser" }),
    );

    expect(openHtmlFile).toHaveBeenCalledWith(options);
  });

  it("retains static content and explains why its scripts are unavailable", () => {
    const content = [
      "<h1>Sales report</h1>",
      '<button onclick="updateChart()">Update</button>',
      '<input value="report">',
      '<a href="https://example.com" target="_blank">Details</a>',
      '<form action="/submit" method="post"></form>',
      '<meta http-equiv="refresh" content="5">',
      '<p contenteditable="true">Report summary</p>',
      '<script src="chart.js"></script>',
    ].join("\n");
    render(<FilePreview filePath="report.html" content={content} />);

    const frame = screen.getByTitle("files.htmlPreview");
    expect(frame).toHaveAttribute("sandbox", "");
    expect(frame).toHaveAttribute("tabindex", "-1");
    expect(screen.getByRole("status")).toHaveTextContent(
      "files.htmlReadOnlyNotice",
    );
    const document = new DOMParser().parseFromString(
      frame.getAttribute("srcdoc") ?? "",
      "text/html",
    );
    expect(document.querySelector("h1")?.textContent).toBe("Sales report");
    expect(document.querySelector("script")).toBeNull();
    expect(document.querySelector("[onclick]")).toBeNull();
    expect(document.querySelector("meta[http-equiv='refresh']")).toBeNull();
    expect(document.querySelector("[contenteditable]")).toBeNull();
    expect(document.querySelector("button")?.getAttribute("disabled")).toBe("");
    expect(document.querySelector("input")?.getAttribute("disabled")).toBe("");
    expect(document.querySelector("a")?.getAttribute("href")).toBeNull();
    expect(document.querySelector("a")?.getAttribute("target")).toBeNull();
    expect(document.querySelector("form")?.getAttribute("action")).toBeNull();
    expect(document.querySelector("form")?.getAttribute("method")).toBeNull();
  });

  it.each([
    '<script type="application/json">{"name":"report"}</script>',
    '<script type="application/ld+json">{"name":"report"}</script>',
    '<script type="importmap">{"imports":{}}</script>',
    "<template><script>draw()</script></template>",
    "<!-- <script>draw()</script> -->",
  ])("does not warn for inert script markup: %s", (script) => {
    render(
      <FilePreview
        filePath="report.html"
        content={`<h1>Static report</h1>${script}`}
      />,
    );

    expect(screen.getByTitle("files.htmlPreview")).toHaveAttribute(
      "sandbox",
      "",
    );
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it.each([
    '<script src="scene.js"></script>',
    '<script type="module">draw()</script>',
    '<script type="text/javascript">draw()</script>',
    '<script type="application/javascript">draw()</script>',
    '<script type="text/ecmascript">draw()</script>',
    '<div onload="draw()"></div>',
  ])("shows the fallback for executable content: %s", (content) => {
    render(<FilePreview filePath="scene.html" content={content} />);

    expect(screen.getByRole("status")).toHaveTextContent(
      "files.htmlReadOnlyNotice",
    );
    expect(screen.queryByTitle("files.htmlPreview")).not.toBeInTheDocument();
  });

  it.each([
    '<img src="photo.png" alt="Rainy street">',
    '<svg><circle cx="20" cy="20" r="10" /></svg>',
  ])("retains native visual content when scripts are present: %s", (image) => {
    render(
      <FilePreview
        filePath="visual.html"
        content={`${image}<script>enhance()</script>`}
      />,
    );

    expect(screen.getByTitle("files.htmlPreview")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "files.htmlReadOnlyNotice",
    );
  });

  it("preserves a page without scripts as a normal static preview", () => {
    render(
      <FilePreview
        filePath="report.html"
        content="<style>body { color: teal; }</style><h1>Static report</h1>"
      />,
    );

    const frame = screen.getByTitle("files.htmlPreview");
    expect(frame).toHaveAttribute("sandbox", "");
    expect(frame.getAttribute("srcdoc")).toContain("Static report");
    expect(frame.getAttribute("srcdoc")).toContain("color: teal");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("updates between static preview and browser guidance as content changes", () => {
    const { rerender } = render(
      <FilePreview filePath="scene.html" content="<h1>Static report</h1>" />,
    );
    expect(screen.getByTitle("files.htmlPreview")).toBeInTheDocument();

    rerender(<FilePreview filePath="scene.html" content={dynamicContent} />);
    expect(screen.queryByTitle("files.htmlPreview")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toBeInTheDocument();

    rerender(
      <FilePreview filePath="scene.html" content="<h1>Updated report</h1>" />,
    );
    expect(
      screen.getByTitle("files.htmlPreview").getAttribute("srcdoc"),
    ).toContain("Updated report");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
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
