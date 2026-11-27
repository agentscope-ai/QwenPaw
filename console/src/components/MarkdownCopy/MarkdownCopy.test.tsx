/**
 * Tests for MarkdownCopy component.
 *
 * Covers:
 * - Renders markdown content in preview mode
 * - Shows controls (switch) when showControls is true
 * - Renders without crash when content is empty
 * - Renders in raw mode when showMarkdown is false
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "@/test/common_setup";

const mockXMarkdownProps: Array<Record<string, unknown>> = [];

// Mock XMarkdown and MermaidCodeBlock to avoid heavy deps
vi.mock("@ant-design/x-markdown", () => ({
  XMarkdown: (props: {
    content: string;
    style?: React.CSSProperties;
    config?: unknown;
  }) => {
    mockXMarkdownProps.push(props);
    return (
      <div data-testid="x-markdown" style={props.style}>
        {props.content}
      </div>
    );
  },
}));

vi.mock("../RenderableCodeBlock", () => ({
  renderableCodeComponents: {},
}));

// Mock useAppMessage hook
const mockMessage = { success: vi.fn(), error: vi.fn() };
vi.mock("../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: mockMessage }),
}));

// Mock clipboard API
Object.defineProperty(navigator, "clipboard", {
  value: { writeText: vi.fn().mockResolvedValue(undefined) },
  writable: true,
  configurable: true,
});

Object.defineProperty(window, "isSecureContext", {
  value: true,
  writable: true,
});

import { MarkdownCopy } from "./MarkdownCopy";
import { DOUBLE_TILDE_MARKED_CONFIG } from "../../utils/markdownStrikethrough";

describe("MarkdownCopy", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockXMarkdownProps.length = 0;
  });

  it("renders markdown content in preview mode by default", () => {
    renderWithProviders(<MarkdownCopy content="# Hello World" />);
    expect(screen.getByTestId("x-markdown")).toHaveStyle({
      backgroundColor: "var(--app-surface)",
      color: "var(--app-text)",
    });
    expect(mockXMarkdownProps[0]?.config).toBe(DOUBLE_TILDE_MARKED_CONFIG);
  });

  it("allows custom markdown viewer styles to override the theme defaults", () => {
    renderWithProviders(
      <MarkdownCopy
        content="# Hello World"
        markdownViewerProps={{
          style: {
            backgroundColor: "transparent",
            color: "inherit",
          },
        }}
      />,
    );

    const markdown = screen.getByTestId("x-markdown");
    expect(markdown.style.backgroundColor).toBe("transparent");
    expect(markdown.style.color).toBe("inherit");
  });

  it("shows switch control when showControls is true", () => {
    renderWithProviders(<MarkdownCopy content="test" showControls />);
    expect(screen.getByRole("switch")).toBeInTheDocument();
  });

  it("renders without crash when content is empty", () => {
    renderWithProviders(<MarkdownCopy content="" />);
    expect(screen.getByTestId("x-markdown")).toBeInTheDocument();
  });

  it("renders textarea when showMarkdown is false", () => {
    renderWithProviders(
      <MarkdownCopy content="raw text" showMarkdown={false} />,
    );
    expect(screen.getByRole("textbox")).toBeInTheDocument();
  });
});
