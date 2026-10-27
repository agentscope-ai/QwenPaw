// @vitest-environment jsdom
/**
 * Contract tests for AppendFileCard.
 *
 * Same family as WriteFileCard but for an append: the badge counts only the
 * lines that were added to the file, and it stays hidden while the append is
 * still being streamed. The title falls back through file_path → path →
 * default exactly like its sibling, which is pinned separately here because the
 * two cards must not drift apart.
 *
 * There was no test file for this card before this one.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ToolCallContent } from "../shared/types";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) =>
      options ? `${key}[${JSON.stringify(options)}]` : key,
  }),
}));

vi.mock("../shared", () => ({
  ToolCardShell: ({
    title,
    badges,
    summaryAction,
    children,
  }: {
    title?: string;
    badges?: React.ReactNode;
    summaryAction?: React.ReactNode;
    children?: React.ReactNode;
  }) => (
    <div>
      <span data-testid="card-title">{title}</span>
      {badges ? <div data-testid="badges">{badges}</div> : null}
      {summaryAction ? (
        <div data-testid="summary-action">{summaryAction}</div>
      ) : null}
      <div data-testid="card-body">{children}</div>
    </div>
  ),
  DefaultBlock: ({ content }: { content?: string }) => (
    <pre data-testid="block-Content">{content}</pre>
  ),
  FileAttachmentPreview: () => <div data-testid="file-attachment" />,
  FilePreviewLink: () => <button data-testid="file-preview-link" />,
}));

vi.mock("../shared/utils", () => ({
  shortFileName: (path: unknown) => (path ? `SHORT(${path})` : ""),
  countLines: (text: unknown) =>
    typeof text === "string" && text ? text.split("\n").length : 0,
}));

import AppendFileCard from "./AppendFileCard";

const NO_PARAMS = undefined as unknown as Record<string, unknown>;

const createContent = (
  overrides: Partial<ToolCallContent> = {},
): ToolCallContent => ({
  type: "tool_call",
  id: "append-1",
  name: "append_file",
  status: "done",
  params: { file_path: "log.md", content: "appended one\nappended two" },
  ...overrides,
});

const titleText = () => screen.getByTestId("card-title").textContent;
const badgesText = () => screen.queryByTestId("badges")?.textContent;

describe("AppendFileCard", () => {
  it("names the appended file in the title", () => {
    render(<AppendFileCard content={createContent()} />);

    expect(titleText()).toBe('tool.appendFile[{"file":"SHORT(log.md)"}]');
  });

  it("falls back to the path param when file_path is absent", () => {
    render(
      <AppendFileCard
        content={createContent({ params: { path: "log.md", content: "x" } })}
      />,
    );

    expect(titleText()).toBe('tool.appendFile[{"file":"SHORT(log.md)"}]');
  });

  it("uses the default title when the call names no file", () => {
    render(
      <AppendFileCard content={createContent({ params: { content: "x" } })} />,
    );

    expect(titleText()).toBe("tool.appendFileDefault");
  });

  it("uses the default title when the call carries no params", () => {
    render(<AppendFileCard content={createContent({ params: NO_PARAMS })} />);

    expect(titleText()).toBe("tool.appendFileDefault");
  });

  it("counts only the appended lines in the badge", () => {
    render(<AppendFileCard content={createContent()} />);

    expect(badgesText()).toBe('tool.lineBadge.lines[{"count":2}]');
  });

  it("shows no badge when nothing was appended", () => {
    render(
      <AppendFileCard
        content={createContent({
          params: { file_path: "log.md", content: "" },
        })}
      />,
    );

    expect(screen.queryByTestId("badges")).toBeNull();
  });

  it("shows no badge when the call declares no content at all", () => {
    render(
      <AppendFileCard
        content={createContent({ params: { file_path: "log.md" } })}
      />,
    );

    expect(screen.queryByTestId("badges")).toBeNull();
  });

  it("hides the badge while the append is still being streamed", () => {
    render(<AppendFileCard content={createContent({ status: "calling" })} />);

    expect(screen.queryByTestId("badges")).toBeNull();
  });

  it("shows the badge for a finished append even while the message streams", () => {
    render(<AppendFileCard content={createContent()} isStreaming />);

    expect(badgesText()).toContain("tool.lineBadge.lines");
  });

  it("shows the appended text", () => {
    render(<AppendFileCard content={createContent()} />);

    expect(screen.getByTestId("block-Content").textContent).toBe(
      "appended one\nappended two",
    );
  });

  it("renders no content block when nothing was appended", () => {
    render(
      <AppendFileCard
        content={createContent({
          params: { file_path: "log.md", content: "" },
        })}
      />,
    );

    expect(screen.queryByTestId("block-Content")).toBeNull();
  });

  it("renders no content and no preview when the append failed", () => {
    render(<AppendFileCard content={createContent({ status: "error" })} />);

    expect(screen.queryByTestId("badges")).toBeNull();
    expect(screen.queryByTestId("summary-action")).toBeNull();
    expect(screen.queryByTestId("block-Content")).toBeNull();
    expect(screen.queryByTestId("file-attachment")).toBeNull();
  });

  it("offers the file preview next to a successful append", () => {
    render(<AppendFileCard content={createContent()} />);

    expect(screen.getByTestId("file-preview-link")).toBeInTheDocument();
    expect(screen.getByTestId("file-attachment")).toBeInTheDocument();
  });
});
