import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PageShell } from ".";

describe("PageShell", () => {
  it("renders one visible page title and the header slots", () => {
    render(
      <PageShell
        title="Models"
        center={<span>scope</span>}
        extra={<button type="button">add</button>}
        subRow={<span>description</span>}
      >
        <p>content</p>
      </PageShell>,
    );

    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByRole("heading", { name: "Models" })).toBeVisible();
    expect(screen.getByText("scope")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "add" })).toBeInTheDocument();
    expect(screen.getByText("description")).toBeInTheDocument();
  });

  it("supports a screen-reader-only title in compatibility mode", () => {
    render(
      <PageShell title="Chat" mode="compat">
        <div>existing page</div>
      </PageShell>,
    );

    const title = screen.getByRole("heading", { name: "Chat" });
    expect(title).toHaveAttribute("data-page-title", "sr-only");
    expect(screen.getByText("existing page")).toBeInTheDocument();
  });

  it("does not create a second h1 when shells are nested", () => {
    render(
      <PageShell title="Outer">
        <PageShell title="Inner">
          <p>content</p>
        </PageShell>
      </PageShell>,
    );

    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByRole("heading", { name: "Outer" })).toBeInTheDocument();
  });
});
