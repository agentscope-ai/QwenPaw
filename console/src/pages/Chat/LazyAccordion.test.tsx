import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import LazyAccordion from "./LazyAccordion";

vi.mock("@agentscope-ai/chat", () => ({
  Accordion: ({
    children,
    open,
    title,
  }: {
    children: React.ReactNode;
    open: boolean;
    title: string;
  }) => (
    <div data-testid="vendor-shell">
      <div
        className={`sdk-accordion-group sdk-accordion-group-${
          open ? "open" : "close"
        }`}
      >
        <button
          className={`sdk-accordion-group-header-${open ? "open" : "close"}`}
          type="button"
        >
          {title}
        </button>
        <div>{children}</div>
      </div>
    </div>
  ),
}));

describe("LazyAccordion", () => {
  it("does not render process children until the closed group is opened", () => {
    const renderChildren = vi.fn(() => <div>expensive process content</div>);

    render(<LazyAccordion title="4 steps" renderChildren={renderChildren} />);

    expect(renderChildren).not.toHaveBeenCalled();
    expect(screen.queryByText("expensive process content")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "4 steps" }));

    expect(renderChildren).toHaveBeenCalledTimes(1);
    expect(screen.getByText("expensive process content")).toBeInTheDocument();
  });

  it("does not depend on the vendor group being a direct wrapper child", () => {
    render(
      <LazyAccordion
        title="Wrapped group"
        renderChildren={() => <div>wrapped content</div>}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Wrapped group" }));

    expect(screen.getByText("wrapped content")).toBeInTheDocument();
  });

  it("unmounts process children when the group closes again", () => {
    const renderChildren = vi.fn(() => <div>process content</div>);

    render(
      <LazyAccordion
        defaultOpen
        title="Running"
        renderChildren={renderChildren}
      />,
    );
    expect(screen.getByText("process content")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Running" }));

    expect(screen.queryByText("process content")).toBeNull();
  });

  it("ignores clicks on an accordion nested inside process content", () => {
    render(
      <LazyAccordion
        defaultOpen
        title="Outer steps"
        renderChildren={() => (
          <div className="sdk-accordion-group">
            <button className="sdk-accordion-group-header-close" type="button">
              Nested tool
            </button>
          </div>
        )}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Nested tool" }));

    expect(screen.getByRole("button", { name: "Nested tool" })).toBeVisible();
  });
});
