import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import FilePreview from "./FilePreview";

const office = vi.hoisted(() => ({
  docxToHtml: vi.fn(),
  readXlsx: vi.fn(),
  readPptx: vi.fn(),
}));

vi.mock("./officeDocument", () => office);

function stubFetch(body: BlobPart = "office-bytes") {
  const fetchSpy = vi.fn().mockResolvedValue({
    ok: true,
    blob: () => Promise.resolve(new Blob([body])),
  });
  vi.stubGlobal("fetch", fetchSpy);
  return fetchSpy;
}

describe("FilePreview office documents", () => {
  beforeEach(() => {
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:office");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    // jsdom's Blob predates arrayBuffer() in some versions.
    if (!Blob.prototype.arrayBuffer) {
      Blob.prototype.arrayBuffer = function () {
        return Promise.resolve(new ArrayBuffer(this.size));
      };
    }
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    Object.values(office).forEach((mock) => mock.mockReset());
  });

  it("renders sanitised docx html without active content or live links", async () => {
    stubFetch();
    office.docxToHtml.mockResolvedValue(
      '<h1>Quarterly report</h1><p onclick="alert(1)">Body ' +
        '<a href="https://example.com">link</a></p><script>alert(2)</script>' +
        '<img src="x" onerror="alert(3)">',
    );
    const { container } = render(
      <FilePreview filePath="report.docx" content="" />,
    );

    expect(
      await screen.findByRole("heading", { name: "Quarterly report" }),
    ).toBeInTheDocument();
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("[onclick], [onerror]")).toBeNull();
    expect(container.querySelector("a")?.hasAttribute("href")).toBe(false);
  });

  it("fetches workspace Office files through the authenticated download url", async () => {
    const fetchSpy = stubFetch();
    office.docxToHtml.mockResolvedValue("<p>ok</p>");
    render(
      <FilePreview filePath="out/report.docx" content="" chatId="chat-1" />,
    );
    await screen.findByText("ok");
    expect(fetchSpy.mock.calls[0][0]).toContain("report.docx");
    expect(fetchSpy.mock.calls[0][1].headers).toMatchObject({
      "X-Chat-Id": "chat-1",
    });
  });

  it("renders xlsx sheets as tables and switches between sheet tabs", async () => {
    stubFetch();
    office.readXlsx.mockResolvedValue([
      {
        name: "Revenue",
        rows: [
          ["Region", "Total"],
          ["EMEA", "42"],
        ],
        totalRows: 2,
        totalCols: 2,
      },
      { name: "Notes", rows: [["Remember"]], totalRows: 1, totalCols: 1 },
    ]);
    render(<FilePreview filePath="budget.xlsx" content="" />);

    expect(await screen.findByText("EMEA")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Notes" }));
    expect(screen.getByText("Remember")).toBeInTheDocument();
    expect(screen.queryByText("EMEA")).not.toBeInTheDocument();
  });

  it("notes when a sheet was truncated", async () => {
    stubFetch();
    office.readXlsx.mockResolvedValue([
      { name: "Big", rows: [["a"]], totalRows: 9000, totalCols: 1 },
    ]);
    render(<FilePreview filePath="big.xlsx" content="" />);
    await screen.findByText("a");
    expect(screen.getByText("files.officeSheetTruncated")).toBeInTheDocument();
  });

  it("renders pptx slides in presentation order", async () => {
    stubFetch();
    office.readPptx.mockResolvedValue([
      { index: 1, paragraphs: ["Roadmap", "Q1 goals"] },
      { index: 2, paragraphs: ["Thanks"] },
    ]);
    render(<FilePreview filePath="deck.pptx" content="" />);

    expect(await screen.findByText("Roadmap")).toBeInTheDocument();
    expect(screen.getByText("Q1 goals")).toBeInTheDocument();
    expect(screen.getAllByRole("heading").map((h) => h.textContent)).toEqual([
      "files.officeSlide",
      "files.officeSlide",
    ]);
  });

  it("falls back to the unavailable message when the document is corrupt", async () => {
    stubFetch();
    office.readPptx.mockRejectedValue(new Error("bad zip"));
    await act(async () => {
      render(<FilePreview filePath="broken.pptx" content="" />);
    });
    await waitFor(() =>
      expect(screen.getByText("files.previewUnavailable")).toBeInTheDocument(),
    );
  });

  it("falls back to the unavailable message when the download fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 404 }),
    );
    render(<FilePreview filePath="gone.docx" content="" />);
    expect(
      await screen.findByText("files.previewUnavailable"),
    ).toBeInTheDocument();
    expect(office.docxToHtml).not.toHaveBeenCalled();
  });
});
