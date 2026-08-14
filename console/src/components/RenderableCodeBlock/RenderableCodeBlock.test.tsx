import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ThemeProvider } from "../../contexts/ThemeContext";
import { RenderableCodeBlock } from "./RenderableCodeBlock";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) =>
      ({
        "common.copied": "Copied",
        "common.copy": "Copy",
        "common.download": "Download",
        "common.preview": "Preview",
        "common.raw": "Raw",
      })[key] || key,
  }),
}));

vi.mock("../MermaidCodeBlock", () => ({
  MermaidCodeBlock: ({ chart }: { chart: string }) => (
    <div data-testid="mermaid-preview">{chart}</div>
  ),
}));

describe("RenderableCodeBlock", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.classList.remove("dark-mode");
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("renders LaTeX preview by default and exposes the raw source", () => {
    const source = String.raw`\int_0^1 x^2 dx`;
    const { container } = render(
      <RenderableCodeBlock block lang="latex">
        {source}
      </RenderableCodeBlock>,
    );

    expect(container.querySelector(".katex")).toBeInTheDocument();
    expect(screen.getByText("Preview").closest("button")).toHaveAttribute(
      "aria-selected",
      "true",
    );

    fireEvent.click(screen.getByText("Raw"));

    expect(container.querySelector("[role='tabpanel']")).toHaveTextContent(
      source,
    );
    expect(screen.getByText("Raw").closest("button")).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("links the tabs to their panel and supports keyboard navigation", () => {
    render(
      <RenderableCodeBlock block lang="latex">
        {String.raw`x^2`}
      </RenderableCodeBlock>,
    );

    const previewTab = screen.getByRole("tab", { name: "Preview" });
    const rawTab = screen.getByRole("tab", { name: "Raw" });
    const panel = screen.getByRole("tabpanel");

    expect(previewTab).toHaveAttribute("aria-controls", panel.id);
    expect(panel).toHaveAttribute("aria-labelledby", previewTab.id);
    expect(previewTab).toHaveAttribute("tabindex", "0");
    expect(rawTab).toHaveAttribute("tabindex", "-1");

    previewTab.focus();
    fireEvent.keyDown(previewTab, { key: "ArrowRight" });

    expect(rawTab).toHaveFocus();
    expect(rawTab).toHaveAttribute("aria-selected", "true");
    expect(rawTab).toHaveAttribute("tabindex", "0");
    expect(panel).toHaveAttribute("aria-labelledby", rawTab.id);

    fireEvent.keyDown(rawTab, { key: "Home" });
    expect(previewTab).toHaveFocus();
    expect(previewTab).toHaveAttribute("aria-selected", "true");
  });

  it.each(["tex", "math"])("treats %s as a LaTeX alias", (lang) => {
    const { container } = render(
      <RenderableCodeBlock block lang={lang}>
        {String.raw`x^2`}
      </RenderableCodeBlock>,
    );

    expect(container.querySelector("[data-language='latex']")).toBeTruthy();
    expect(container.querySelector(".katex")).toBeInTheDocument();
  });

  it("renders Mermaid preview and keeps its source available", () => {
    const source = "graph TD; A-->B";
    render(
      <RenderableCodeBlock block lang="mermaid">
        {source}
      </RenderableCodeBlock>,
    );

    expect(screen.getByTestId("mermaid-preview")).toHaveTextContent(source);
    fireEvent.click(screen.getByText("Raw"));
    expect(screen.getByRole("tabpanel")).toHaveTextContent(source);
  });

  it("shows a concise error state for invalid LaTeX", () => {
    render(
      <RenderableCodeBlock block lang="latex">
        {String.raw`\invalidCommand{`}
      </RenderableCodeBlock>,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Unable to render formula",
    );
    expect(screen.getByRole("tab", { name: "Raw" })).toBeEnabled();
  });

  it("keeps ordinary code blocks in source-only mode", () => {
    const { container } = render(
      <RenderableCodeBlock block lang="typescript">
        {"const answer = 42;"}
      </RenderableCodeBlock>,
    );

    expect(
      container.querySelector("[data-language='typescript']"),
    ).toHaveTextContent("const answer = 42;");
    expect(container.querySelector("section")).toHaveClass(
      "qwenpaw-code-block",
    );
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Download" })).toBeEnabled();
  });

  it("keeps inline code HTML attributes and omits renderer-only props", () => {
    const handleClick = vi.fn();

    render(
      <RenderableCodeBlock
        data-source="markdown"
        domNode={{} as never}
        onClick={handleClick}
        streamStatus="done"
        title="Inline source"
      >
        inline
      </RenderableCodeBlock>,
    );

    const code = screen.getByTitle("Inline source");
    expect(code).toHaveAttribute("data-source", "markdown");
    expect(code).not.toHaveAttribute("domNode");
    expect(code).not.toHaveAttribute("streamStatus");

    fireEvent.click(code);
    expect(handleClick).toHaveBeenCalledOnce();
  });

  it("releases download URLs after the browser can start the download", () => {
    vi.useFakeTimers();
    const createObjectURL = vi.fn(() => "blob:qwenpaw-code");
    const revokeObjectURL = vi.fn();
    const anchorClick = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);
    vi.stubGlobal("URL", { createObjectURL, revokeObjectURL });

    render(
      <RenderableCodeBlock block lang="python">
        {"answer = 42"}
      </RenderableCodeBlock>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Download" }));

    expect(createObjectURL).toHaveBeenCalledOnce();
    expect(anchorClick).toHaveBeenCalledOnce();
    expect(document.querySelector("a[download='block.py']")).toBeNull();
    expect(revokeObjectURL).not.toHaveBeenCalled();

    vi.runOnlyPendingTimers();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:qwenpaw-code");
  });

  it.each([
    ["light", "hsl(230, 8%, 24%)", false],
    ["dark", "hsl(220, 14%, 71%)", true],
  ] as const)(
    "uses the %s syntax theme without an inner code background",
    (theme, color, isDark) => {
      localStorage.setItem("qwenpaw-theme", theme);
      const { container } = render(
        <ThemeProvider>
          <RenderableCodeBlock block lang="python">
            {"answer = 42"}
          </RenderableCodeBlock>
        </ThemeProvider>,
      );
      const pre = container.querySelector("pre");
      const code = container.querySelector("code");

      expect(pre).toHaveStyle({ color });
      expect(code).toHaveStyle({ background: "transparent" });
      expect(document.documentElement.classList.contains("dark-mode")).toBe(
        isDark,
      );
    },
  );
});
