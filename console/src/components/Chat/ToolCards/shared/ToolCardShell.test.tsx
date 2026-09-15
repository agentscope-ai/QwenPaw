// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

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
    recordMissing: false,
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
import { adaptCardForV1 } from "../adapters/v1Adapter";
import ShellCard from "../cards/ShellCard";
import ReadFileCard from "../cards/ReadFileCard";
import WriteFileCard from "../cards/WriteFileCard";
import SendFileCard from "../cards/SendFileCard";
import GenericToolCard from "../cards/GenericToolCard";

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

const streamingInputContent: ToolCallContent = {
  ...runningContent,
  inputProgress: {
    preview: '{"path":"notes.txt"}',
    truncated: false,
  },
};

describe("ToolCardShell interruption", () => {
  it.each([
    ShellCard,
    ReadFileCard,
    WriteFileCard,
    SendFileCard,
    GenericToolCard,
  ])(
    "preserves interruption through the registered %s renderer",
    (CardComponent) => {
      const Card = adaptCardForV1(CardComponent);
      render(
        <Card
          data={{
            status: "completed",
            content: [
              {
                data: { name: "any_tool", call_id: "call-1", arguments: "{}" },
              },
              { data: { state: "interrupted", output: "partial output" } },
            ],
          }}
        />,
      );
      expect(screen.getByText("tool.interrupted")).toBeInTheDocument();
      expect(screen.queryByText("Error")).not.toBeInTheDocument();
    },
  );

  it("replaces the running state with a neutral interruption and keeps diagnostics", () => {
    const result =
      "first step finished\n<system-reminder>interrupted</system-reminder>";
    const { container, rerender } = render(
      <ToolCardShell
        content={runningContent}
        icon={<span />}
        title="Tool"
        isStreaming
      />,
    );
    expect(
      container.querySelector('[class*="toolCallSpinner"]'),
    ).not.toBeNull();
    rerender(
      <ToolCardShell
        content={{ ...runningContent, status: "interrupted", result }}
        icon={<span />}
        title="Tool"
        isStreaming
        defaultExpanded
        inlineResult="success result"
        badges={<span>success badge</span>}
        summaryAction={<button>success action</button>}
      >
        <div>success body</div>
      </ToolCardShell>,
    );
    expect(screen.getByText("tool.interrupted")).toBeInTheDocument();
    expect(screen.getByText("tool.interruptedDescription")).toBeInTheDocument();
    expect(container.querySelector('[class*="toolCallSpinner"]')).toBeNull();
    expect(
      container.querySelector('[class*="toolCallCompactError"]'),
    ).toBeNull();
    expect(screen.queryByText("Error")).not.toBeInTheDocument();
    for (const text of [
      "success result",
      "success badge",
      "success action",
      "success body",
    ]) {
      expect(screen.queryByText(text)).not.toBeInTheDocument();
    }
    const diagnostics = screen
      .getByText("tool.interruptedOutput")
      .closest("details");
    expect(diagnostics).not.toHaveAttribute("open");
    diagnostics!.open = true;
    fireEvent(diagnostics!, new Event("toggle"));
    expect(diagnostics).toHaveTextContent("first step finished");
    expect(diagnostics).toHaveTextContent(
      "<system-reminder>interrupted</system-reminder>",
    );
  });

  it("does not fabricate output when an interrupted tool returned nothing", () => {
    render(
      <ToolCardShell
        content={{ ...content, status: "interrupted", result: "" }}
        icon={<span />}
        title="Tool"
        defaultExpanded
      />,
    );
    expect(screen.getByText("tool.interrupted")).toBeInTheDocument();
    expect(
      screen.queryByText("tool.interruptedOutput"),
    ).not.toBeInTheDocument();
  });

  it("keeps structured partial output intact in diagnostics", () => {
    const result = [
      { type: "text", text: "partial" },
      { type: "image", data: "image-payload" },
    ];
    render(
      <ToolCardShell
        content={{ ...content, status: "interrupted", result }}
        icon={<span />}
        title="Tool"
        defaultExpanded
      />,
    );
    const diagnostics = screen
      .getByText("tool.interruptedOutput")
      .closest("details");
    expect(diagnostics).toHaveTextContent("partial");
    expect(diagnostics).toHaveTextContent("image-payload");
  });

  it("continues to show genuine execution errors as errors", () => {
    const { container } = render(
      <ToolCardShell
        content={{ ...content, status: "error", result: "permission denied" }}
        icon={<span />}
        title="Tool"
        defaultExpanded
      />,
    );
    expect(screen.getByText("Error")).toBeInTheDocument();
    expect(container).toHaveTextContent("permission denied");
    expect(screen.queryByText("tool.interrupted")).not.toBeInTheDocument();
  });
});

describe("ToolCardShell lazy body", () => {
  beforeEach(() => {
    localStorage.removeItem("qwenpaw_tool_calls_default_expanded");
    localStorage.removeItem("qwenpaw_tool_display_mode");
  });

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

  it("shows raw input and output after opening a raw-mode card", () => {
    localStorage.setItem("qwenpaw_tool_display_mode", "raw-input-output");
    const rawContent: ToolCallContent = {
      ...content,
      rawInput: '{"command":"pwd"}',
      params: { command: "pwd" },
      result: { stdout: "/workspace" },
    };

    const { container } = render(
      <ToolCardShell content={rawContent} icon={<span />} title="Ordinary tool">
        <div>processed output</div>
      </ToolCardShell>,
    );

    const details = container.querySelector("details");
    expect(details).not.toHaveAttribute("open");
    expect(screen.queryByText("Input")).not.toBeInTheDocument();

    details!.open = true;
    fireEvent(details!, new Event("toggle"));

    expect(screen.getByText("Input")).toBeInTheDocument();
    expect(screen.getByText("Output")).toBeInTheDocument();
    expect(screen.getByText(/command/)).toBeInTheDocument();
    expect(screen.getByText(/workspace/)).toBeInTheDocument();
    expect(screen.queryByText("processed output")).not.toBeInTheDocument();
  });

  it("does not auto-open media cards in raw mode", () => {
    localStorage.setItem("qwenpaw_tool_display_mode", "raw-input-output");

    const { container } = render(
      <ToolCardShell
        content={content}
        icon={<span />}
        title="Send file"
        defaultExpanded
      >
        <div>hello.txt</div>
      </ToolCardShell>,
    );

    expect(container.querySelector("details")).not.toHaveAttribute("open");
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

  it("replaces the spinner node when the tool finishes", () => {
    const { container, rerender } = render(
      <ToolCardShell
        content={runningContent}
        icon={<span data-testid="completion-icon" />}
        title="Shell"
        isStreaming
      />,
    );
    const spinner = container.querySelector('[class*="toolCallSpinner"]');

    expect(spinner).not.toBeNull();

    rerender(
      <ToolCardShell
        content={content}
        icon={<span data-testid="completion-icon" />}
        title="Shell"
      />,
    );

    const completionIcon = screen.getByTestId("completion-icon");
    expect(spinner).not.toBeInTheDocument();
    expect(completionIcon.parentElement).not.toBe(spinner);
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

  it("keeps streaming input quiet in the summary and preserves its preview", () => {
    const { container } = render(
      <ToolCardShell
        content={streamingInputContent}
        icon={<span />}
        title="Read file"
        isStreaming
        defaultExpanded
      />,
    );

    const summary = container.querySelector("summary");
    expect(summary).toHaveTextContent("tool.loading");
    expect(summary).not.toHaveTextContent("tool.inputProgress");
    const previewTitle = screen.getByText("tool.rawInputPreview");
    const previewBlock = previewTitle.parentElement?.parentElement;
    expect(previewBlock).toHaveTextContent("path");
    expect(previewBlock).toHaveTextContent("notes.txt");
  });
});
