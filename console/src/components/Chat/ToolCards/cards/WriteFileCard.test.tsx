// @vitest-environment jsdom
/**
 * Contract tests for WriteFileCard.
 *
 * The card tells the user which file was written, how many lines it holds, and
 * what went in. The line-count badge deliberately hides while the write is still
 * being streamed (a half-written file has no meaningful length), which is the
 * one piece of timing logic in this component and is pinned here.
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

import WriteFileCard from "./WriteFileCard";

const NO_PARAMS = undefined as unknown as Record<string, unknown>;

const createContent = (
  overrides: Partial<ToolCallContent> = {},
): ToolCallContent => ({
  type: "tool_call",
  id: "write-1",
  name: "write_file",
  status: "done",
  params: { file_path: "report.md", content: "line one\nline two" },
  ...overrides,
});

const titleText = () => screen.getByTestId("card-title").textContent;
const badgesText = () => screen.queryByTestId("badges")?.textContent;

describe("WriteFileCard", () => {
  it("names the written file in the title", () => {
    render(<WriteFileCard content={createContent()} />);

    expect(titleText()).toBe('tool.writeFile[{"file":"SHORT(report.md)"}]');
  });

  it("falls back to the path param when file_path is absent", () => {
    render(
      <WriteFileCard
        content={createContent({ params: { path: "notes.md", content: "hi" } })}
      />,
    );

    expect(titleText()).toBe('tool.writeFile[{"file":"SHORT(notes.md)"}]');
  });

  it("uses the default title when the call names no file", () => {
    render(
      <WriteFileCard content={createContent({ params: { content: "hi" } })} />,
    );

    expect(titleText()).toBe("tool.writeFileDefault");
  });

  it("uses the default title when the call carries no params", () => {
    render(<WriteFileCard content={createContent({ params: NO_PARAMS })} />);

    expect(titleText()).toBe("tool.writeFileDefault");
  });

  it("counts the written lines in the badge", () => {
    render(<WriteFileCard content={createContent()} />);

    expect(badgesText()).toBe('tool.lineBadge.lines[{"count":2}]');
  });

  it("shows no badge for a file written empty", () => {
    render(
      <WriteFileCard
        content={createContent({
          params: { file_path: "empty.md", content: "" },
        })}
      />,
    );

    expect(screen.queryByTestId("badges")).toBeNull();
  });

  it("shows no badge when the call declares no content at all", () => {
    render(
      <WriteFileCard
        content={createContent({ params: { file_path: "empty.md" } })}
      />,
    );

    expect(screen.queryByTestId("badges")).toBeNull();
  });

  it("hides the badge while the write is still being streamed", () => {
    render(<WriteFileCard content={createContent({ status: "calling" })} />);

    expect(screen.queryByTestId("badges")).toBeNull();
  });

  it("shows the badge once the streamed write has settled", () => {
    render(<WriteFileCard content={createContent()} isStreaming />);

    expect(badgesText()).toContain("tool.lineBadge.lines");
  });

  it("shows what was written", () => {
    render(<WriteFileCard content={createContent()} />);

    expect(screen.getByTestId("block-Content").textContent).toBe(
      "line one\nline two",
    );
  });

  it("renders no content block for a file written empty", () => {
    render(
      <WriteFileCard
        content={createContent({
          params: { file_path: "empty.md", content: "" },
        })}
      />,
    );

    expect(screen.queryByTestId("block-Content")).toBeNull();
  });

  it("renders no content and no preview when the write failed", () => {
    render(<WriteFileCard content={createContent({ status: "error" })} />);

    expect(screen.queryByTestId("badges")).toBeNull();
    expect(screen.queryByTestId("summary-action")).toBeNull();
    expect(screen.queryByTestId("block-Content")).toBeNull();
    expect(screen.queryByTestId("file-attachment")).toBeNull();
  });

  it("offers the file preview next to a successful write", () => {
    render(<WriteFileCard content={createContent()} />);

    expect(screen.getByTestId("file-preview-link")).toBeInTheDocument();
    expect(screen.getByTestId("file-attachment")).toBeInTheDocument();
  });
});
