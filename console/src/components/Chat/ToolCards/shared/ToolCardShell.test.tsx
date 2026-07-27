/**
 * Tests for ToolCardShell lazy body mounting.
 *
 * `<details>` only hides content visually, so the shell must not mount
 * its body (children / error blocks) until the card is first expanded;
 * afterwards the body stays mounted to preserve internal state.
 */
// @vitest-environment jsdom
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock("./DefaultBlock", () => ({
  default: ({ title, content }: { title: string; content: string }) => (
    <div data-testid={`block-${title}`}>{content}</div>
  ),
}));

import ToolCardShell from "./ToolCardShell";
import type { ToolCallContent } from "./types";

function makeContent(overrides?: Partial<ToolCallContent>): ToolCallContent {
  return {
    type: "tool_call",
    id: "call-1",
    name: "view_image",
    params: { path: "a.png" },
    result: "ok",
    status: "done",
    ...overrides,
  };
}

function expandCard(container: HTMLElement) {
  const details = container.querySelector("details")!;
  details.open = true;
  fireEvent(details, new Event("toggle", { bubbles: true }));
}

describe("ToolCardShell lazy body", () => {
  it("does not mount children while collapsed", () => {
    render(
      <ToolCardShell content={makeContent()} icon={<span />} title="card">
        <div data-testid="body">heavy body</div>
      </ToolCardShell>,
    );

    expect(screen.getByText("card")).toBeInTheDocument();
    expect(screen.queryByTestId("body")).not.toBeInTheDocument();
  });

  it("mounts children on first expand and keeps them after collapse", () => {
    const { container } = render(
      <ToolCardShell content={makeContent()} icon={<span />} title="card">
        <div data-testid="body">heavy body</div>
      </ToolCardShell>,
    );

    expandCard(container);
    expect(screen.getByTestId("body")).toBeInTheDocument();

    // Collapsing again must not unmount the body (state preservation).
    const details = container.querySelector("details")!;
    details.open = false;
    fireEvent(details, new Event("toggle", { bubbles: true }));
    expect(screen.getByTestId("body")).toBeInTheDocument();
  });

  it("mounts error blocks only after expand", () => {
    const { container } = render(
      <ToolCardShell
        content={makeContent({ status: "error", result: "boom" })}
        icon={<span />}
        title="card"
      />,
    );

    expect(screen.queryByTestId("block-Input")).not.toBeInTheDocument();
    expect(screen.queryByTestId("block-Error")).not.toBeInTheDocument();

    expandCard(container);
    expect(screen.getByTestId("block-Input")).toBeInTheDocument();
    expect(screen.getByTestId("block-Error")).toHaveTextContent("boom");
  });
});
