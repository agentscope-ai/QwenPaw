// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("./ToolCallSessionContext", () => ({
  useToolCallSessionId: () => "",
}));

vi.mock("../../../../hooks/useToolCallControl", () => ({
  useToolCallControl: () => ({
    bannerVisible: false,
    offloadRemaining: 12,
    killRemaining: 30,
    defaultPolicy: "keep_foreground",
    maxInternalTimeoutSecs: null,
    elapsed: 0,
    toggleBanner: vi.fn(),
    closeBanner: vi.fn(),
    updateRemaining: vi.fn(),
  }),
}));

vi.mock("./ToolCallControlPopover", () => ({
  OffloadBanner: () => null,
}));

import ToolCardShell from "./ToolCardShell";
import type { ToolCallContent } from "./types";

const content: ToolCallContent = {
  type: "tool_call",
  id: "call-1",
  name: "execute_shell_command",
  params: {},
  result: "output",
  status: "done",
};

const runningContent: ToolCallContent = {
  ...content,
  params: { command: "python verbose_script.py" },
  status: "calling",
};

describe("ToolCardShell lazy body", () => {
  it("opens file-facing results by default when requested", () => {
    render(
      <ToolCardShell
        content={content}
        icon={<span />}
        title="Send file"
        defaultExpanded
      >
        <div>hello.txt</div>
      </ToolCardShell>,
    );

    const details = screen.getByText("hello.txt").closest("details");
    expect(details).toHaveAttribute("open");
  });

  it("keeps ordinary tool details collapsed and unmounted", () => {
    const { container } = render(
      <ToolCardShell content={content} icon={<span />} title="Ordinary tool">
        <div>raw output</div>
      </ToolCardShell>,
    );

    expect(container.querySelector("details")).not.toHaveAttribute("open");
    expect(screen.queryByText("raw output")).not.toBeInTheDocument();
  });

  it("does not toggle the tool when its summary action is clicked", () => {
    const { container } = render(
      <ToolCardShell
        content={content}
        icon={<span />}
        title="Read file"
        summaryAction={
          <button
            type="button"
            onClick={(event) => {
              event.preventDefault();
              event.stopPropagation();
            }}
          >
            Preview
          </button>
        }
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(container.querySelector("details")).not.toHaveAttribute("open");
  });

  it("keeps the full tool title available when the label is truncated", () => {
    const title = `Run ${"long-command-argument ".repeat(40)}`;

    const { container } = render(
      <ToolCardShell content={content} icon={<span />} title={title} />,
    );
    const label = container.querySelector(`[title]`);

    expect(label).not.toBeNull();
    expect(label).toHaveAttribute("title", title);
    expect(label).toHaveTextContent(title.trim());
  });

  it("mounts the body only after the first expansion", () => {
    const { container } = render(
      <ToolCardShell content={content} icon={<span />} title="Shell">
        <div>Expensive output</div>
      </ToolCardShell>,
    );

    expect(screen.queryByText("Expensive output")).not.toBeInTheDocument();

    const details = container.querySelector("details");
    expect(details).not.toBeNull();
    details!.open = true;
    fireEvent(details!, new Event("toggle"));

    expect(screen.getByText("Expensive output")).toBeInTheDocument();

    details!.open = false;
    fireEvent(details!, new Event("toggle"));
    expect(screen.getByText("Expensive output")).toBeInTheDocument();
  });

  it("groups Parameters and Runtime in one metadata panel", () => {
    const { container } = render(
      <ToolCardShell
        content={runningContent}
        icon={<span />}
        title="Shell"
        isStreaming
        defaultExpanded
      />,
    );

    const metadata = container.querySelector('[class*="toolCallMetadata"]');
    expect(metadata).not.toBeNull();
    expect(metadata).toHaveTextContent("Parameters");
    expect(metadata).toHaveTextContent("Runtime");
  });
});
