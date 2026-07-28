/**
 * Tests for ToolCardShell lazy body mounting.
 *
 * `<details>` only hides content visually, so the shell must not mount
 * its body until expanded and must release it again after collapse.
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

function toggleCard(container: HTMLElement, open: boolean) {
  const details = container.querySelector("details")!;
  details.open = open;
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

  it("mounts children while expanded and unmounts after collapse", () => {
    const { container } = render(
      <ToolCardShell content={makeContent()} icon={<span />} title="card">
        <div data-testid="body">heavy body</div>
      </ToolCardShell>,
    );

    toggleCard(container, true);
    expect(screen.getByTestId("body")).toBeInTheDocument();

    toggleCard(container, false);
    expect(screen.queryByTestId("body")).not.toBeInTheDocument();
  });

  it("does not invoke an expensive body factory while collapsed", () => {
    const renderBody = vi.fn(() => <div data-testid="body">heavy body</div>);
    const { container } = render(
      <ToolCardShell
        content={makeContent()}
        icon={<span />}
        title="card"
        renderBody={renderBody}
      />,
    );

    expect(renderBody).not.toHaveBeenCalled();
    toggleCard(container, true);
    expect(renderBody).toHaveBeenCalledTimes(1);
    toggleCard(container, false);
    expect(screen.queryByTestId("body")).not.toBeInTheDocument();
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

    toggleCard(container, true);
    expect(screen.getByTestId("block-Input")).toBeInTheDocument();
    expect(screen.getByTestId("block-Error")).toHaveTextContent("boom");
  });
});
