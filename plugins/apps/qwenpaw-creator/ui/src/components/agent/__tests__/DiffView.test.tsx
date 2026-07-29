import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import DiffView from "@/components/agent/DiffView";

describe("DiffView", () => {
  it("renders removed and added lines for text changes", () => {
    render(<DiffView before={"alpha\nbeta"} after={"alpha\ngamma"} />);
    expect(screen.getByText("beta")).toBeInTheDocument();
    expect(screen.getByText("gamma")).toBeInTheDocument();
    expect(document.querySelector('[data-diff-kind="removed"]')).toBeTruthy();
    expect(document.querySelector('[data-diff-kind="added"]')).toBeTruthy();
  });

  it("shows an empty-state message when both sides are empty", () => {
    render(<DiffView before={null} after={null} />);
    expect(screen.getByText("（无内容变化）")).toBeInTheDocument();
  });
});
