import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { InlineMarkdown } from "./InlineMarkdown";

describe("InlineMarkdown", () => {
  it("renders nothing for empty markdown", () => {
    const { container } = render(<InlineMarkdown markdown="" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders strong and inline code without exposing raw markers", () => {
    render(
      <InlineMarkdown markdown="**UltraQA** — use `/ultraqa` for QA cycles" />,
    );

    expect(screen.getByText("UltraQA")).toBeInTheDocument();
    expect(screen.getByText("/ultraqa")).toBeInTheDocument();
    expect(screen.queryByText(/\*\*UltraQA\*\*/)).not.toBeInTheDocument();
    expect(screen.getByText("UltraQA").tagName).toBe("STRONG");
    expect(screen.getByText("/ultraqa").tagName).toBe("CODE");
  });

  it("does not render block constructs from disallowed markup", () => {
    render(<InlineMarkdown markdown={"# Title\n\n**ok**"} />);
    expect(screen.queryByRole("heading")).not.toBeInTheDocument();
    expect(screen.getByText("ok").tagName).toBe("STRONG");
  });

  // -------------------------------------------------------------------------
  // GFM table handling — regression for #3641
  // InlineMarkdown only allows inline elements (p, strong, em, code, del).
  // GFM table syntax should not crash and table content should remain visible
  // through unwrapDisallowed, even though it doesn't render as <table>.
  // -------------------------------------------------------------------------
  it("handles GFM table syntax without crashing (#3641)", () => {
    const tableMarkdown = `| Header 1 | Header 2 |
|----------|----------|
| Cell 1   | Cell 2   |`;
    render(<InlineMarkdown markdown={tableMarkdown} />);
    // Should not crash
    expect(screen.getByText(/Header 1/)).toBeInTheDocument();
    // Table content should be visible (unwrapped from disallowed table elements)
    expect(screen.getByText(/Cell 1/)).toBeInTheDocument();
    expect(screen.getByText(/Cell 2/)).toBeInTheDocument();
    // Should NOT render as <table> (InlineMarkdown only allows inline elements)
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("renders inline formatting within table cells (#3641)", () => {
    const tableMarkdown = `| **Bold** | \`code\` |
|----------|--------|
| normal   | text   |`;
    render(<InlineMarkdown markdown={tableMarkdown} />);
    // Inline formatting should work
    expect(screen.getByText("Bold").tagName).toBe("STRONG");
    expect(screen.getByText("code").tagName).toBe("CODE");
  });
});
