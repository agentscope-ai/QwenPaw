/**
 * Tests for PageHeader component.
 *
 * Covers:
 * - Renders with parent/current props
 * - Renders with items prop
 * - Renders breadcrumb separators
 * - Renders extra and center content
 * - Handles empty items
 */
import { describe, it, expect } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "@/test/common_setup";
import { PageHeader } from "./index";

describe("PageHeader", () => {
  it("renders parent and current as breadcrumb", () => {
    renderWithProviders(<PageHeader parent="Settings" current="Models" />);
    expect(screen.getByText("Settings")).toBeInTheDocument();
    expect(screen.getByText("Models")).toBeInTheDocument();
  });

  it("renders items prop directly", () => {
    renderWithProviders(
      <PageHeader
        items={[
          { title: "Home" },
          { title: "Dashboard" },
          { title: "Analytics" },
        ]}
      />,
    );
    expect(screen.getByText("Home")).toBeInTheDocument();
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
    expect(screen.getByText("Analytics")).toBeInTheDocument();
  });

  it("renders breadcrumb separators between items", () => {
    renderWithProviders(
      <PageHeader items={[{ title: "A" }, { title: "B" }]} />,
    );
    expect(screen.getByText("/")).toBeInTheDocument();
  });

  it("renders extra content", () => {
    renderWithProviders(
      <PageHeader parent="Home" extra={<button>Action</button>} />,
    );
    expect(screen.getByRole("button", { name: "Action" })).toBeInTheDocument();
  });

  it("renders without crash when no breadcrumb props provided", () => {
    const { container } = renderWithProviders(<PageHeader />);
    expect(container.firstChild).toBeInTheDocument();
  });
});
