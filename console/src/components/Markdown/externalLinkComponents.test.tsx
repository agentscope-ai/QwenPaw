/**
 * Tests for the shared external-link markdown renderer.
 *
 * Covers the regression where markdown links opened inside the Tauri WebView
 * (navigating the current window and replacing the whole app):
 * - Clicking a rendered link calls openExternalLink with its href.
 * - The click's default navigation is prevented.
 * - The renderer is applied when passed to <ReactMarkdown> as `components`.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import ReactMarkdown from "react-markdown";

const openExternalLink = vi.fn();
vi.mock("@/utils/openExternalLink", () => ({
  openExternalLink: (...args: unknown[]) => openExternalLink(...args),
}));

import {
  ExternalMarkdownLink,
  externalLinkMarkdownComponents,
} from "./externalLinkComponents";

describe("ExternalMarkdownLink", () => {
  beforeEach(() => {
    openExternalLink.mockReset();
  });

  it("opens the href via openExternalLink and prevents default navigation", () => {
    render(
      <ExternalMarkdownLink href="https://example.com/news">
        news
      </ExternalMarkdownLink>,
    );

    const link = screen.getByText("news");
    const event = new MouseEvent("click", {
      bubbles: true,
      cancelable: true,
    });
    const prevented = !link.dispatchEvent(event);

    expect(prevented).toBe(true);
    expect(openExternalLink).toHaveBeenCalledWith("https://example.com/news");
  });

  it("does not call openExternalLink when href is missing", () => {
    render(<ExternalMarkdownLink>no link</ExternalMarkdownLink>);

    fireEvent.click(screen.getByText("no link"));

    expect(openExternalLink).not.toHaveBeenCalled();
  });

  it("routes markdown-rendered links through openExternalLink", () => {
    render(
      <ReactMarkdown components={externalLinkMarkdownComponents}>
        {"[open](https://example.com/detail)"}
      </ReactMarkdown>,
    );

    fireEvent.click(screen.getByText("open"));

    expect(openExternalLink).toHaveBeenCalledWith("https://example.com/detail");
  });
});
