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
});
