import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PageHeader } from "./index";

describe("PageHeader", () => {
  it("renders current breadcrumb", () => {
    render(<PageHeader current="Settings" />);
    expect(screen.getByText("Settings")).toBeInTheDocument();
  });

  it("renders parent and current with separator", () => {
    render(<PageHeader parent="Home" current="Profile" />);
    expect(screen.getByText("Home")).toBeInTheDocument();
    expect(screen.getByText("Profile")).toBeInTheDocument();
    expect(screen.getByText("/")).toBeInTheDocument();
  });

  it("renders items prop directly", () => {
    render(
      <PageHeader items={[{ title: "A" }, { title: "B" }, { title: "C" }]} />,
    );
    expect(screen.getByText("A")).toBeInTheDocument();
    expect(screen.getByText("B")).toBeInTheDocument();
    expect(screen.getByText("C")).toBeInTheDocument();
  });

  it("renders center slot", () => {
    render(<PageHeader center={<span>Center Content</span>} />);
    expect(screen.getByText("Center Content")).toBeInTheDocument();
  });

  it("renders extra slot", () => {
    render(<PageHeader extra={<button>Action</button>} />);
    expect(screen.getByRole("button", { name: "Action" })).toBeInTheDocument();
  });

  it("renders afterBreadcrumb slot", () => {
    render(<PageHeader current="Page" afterBreadcrumb={<span>tag</span>} />);
    expect(screen.getByText("tag")).toBeInTheDocument();
  });

  it("renders subRow slot", () => {
    render(<PageHeader subRow={<div>Sub Row Content</div>} />);
    expect(screen.getByText("Sub Row Content")).toBeInTheDocument();
  });

  it("applies className prop", () => {
    const { container } = render(<PageHeader className="custom-class" />);
    expect(container.firstChild).toHaveClass("custom-class");
  });

  it("renders nothing for empty items array", () => {
    const { container } = render(<PageHeader items={[]} />);
    expect(container.querySelector(".breadcrumbSeparator")).toBeNull();
  });

  it("skips empty parent/current", () => {
    render(<PageHeader parent="" current="" />);
    expect(screen.queryByText("/")).not.toBeInTheDocument();
  });
});
