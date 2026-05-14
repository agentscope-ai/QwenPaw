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

// Mock XMarkdown and MermaidCodeBlock to avoid heavy deps
vi.mock("@ant-design/x-markdown", () => ({
  XMarkdown: ({ content }: { content: string }) => (
    <div data-testid="x-markdown">{content}</div>
  ),
}));

vi.mock("../MermaidCodeBlock", () => ({
  mermaidComponents: {},
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

describe("MarkdownCopy", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders markdown content in preview mode by default", () => {
    renderWithProviders(<MarkdownCopy content="# Hello World" />);
    expect(screen.getByTestId("x-markdown")).toBeInTheDocument();
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
