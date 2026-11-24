// @vitest-environment jsdom
/**
 * Contract tests for ReadFileCard.
 *
 * The card is how a user reads a file the agent opened: the file name in the
 * title, a line-count badge that only appears once the read finished, and the
 * file contents in the output block. The badge condition (status === "done" and
 * at least one line) is the card's own timing contract and is pinned here for
 * the running, failed, empty and populated cases.
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
    <pre data-testid="block-Output">{content}</pre>
  ),
  FileAttachmentPreview: () => <div data-testid="file-attachment" />,
  FilePreviewLink: () => <button data-testid="file-preview-link" />,
}));

vi.mock("../shared/utils", () => ({
  shortFileName: (path: unknown) => (path ? `SHORT(${path})` : ""),
  countLines: (text: unknown) =>
    typeof text === "string" && text ? text.split("\n").length : 0,
  stringifyResult: (result: unknown) =>
    typeof result === "string" ? result : "",
}));

import ReadFileCard from "./ReadFileCard";

const NO_PARAMS = undefined as unknown as Record<string, unknown>;

const createContent = (
  overrides: Partial<ToolCallContent> = {},
): ToolCallContent => ({
  type: "tool_call",
  id: "read-1",
  name: "read_file",
  status: "done",
  params: { file_path: "config.ts" },
  result: "line one\nline two\nline three",
  ...overrides,
});

const titleText = () => screen.getByTestId("card-title").textContent;
const badgesText = () => screen.queryByTestId("badges")?.textContent;

describe("ReadFileCard", () => {
  it("names the read file in the title", () => {
    render(<ReadFileCard content={createContent()} />);

    expect(titleText()).toBe('tool.readFile[{"file":"SHORT(config.ts)"}]');
  });

  it("falls back to the path param when file_path is absent", () => {
    render(
      <ReadFileCard
        content={createContent({ params: { path: "notes.md" }, result: "x" })}
      />,
    );

    expect(titleText()).toBe('tool.readFile[{"file":"SHORT(notes.md)"}]');
  });

  it("uses the default title when the call names no file", () => {
    render(
      <ReadFileCard content={createContent({ params: {}, result: "x" })} />,
    );

    expect(titleText()).toBe("tool.readFileDefault");
  });

  it("uses the default title when the call carries no params", () => {
    render(<ReadFileCard content={createContent({ params: NO_PARAMS })} />);

    expect(titleText()).toBe("tool.readFileDefault");
  });

  it("counts the read lines in the badge", () => {
    render(<ReadFileCard content={createContent()} />);

    expect(badgesText()).toBe('tool.lineBadge.lines[{"count":3}]');
  });

  it("shows the file contents in the output block", () => {
    render(<ReadFileCard content={createContent()} />);

    expect(screen.getByTestId("block-Output").textContent).toBe(
      "line one\nline two\nline three",
    );
  });

  it("shows no badge and no output block while the read is still running", () => {
    render(
      <ReadFileCard
        content={createContent({ status: "calling", result: "" })}
      />,
    );

    expect(screen.queryByTestId("badges")).toBeNull();
    expect(screen.queryByTestId("block-Output")).toBeNull();
  });

  it("shows no badge when the finished read returned nothing", () => {
    render(<ReadFileCard content={createContent({ result: "" })} />);

    expect(screen.queryByTestId("badges")).toBeNull();
    expect(screen.queryByTestId("block-Output")).toBeNull();
  });

  it("counts a single-line file as one line", () => {
    render(<ReadFileCard content={createContent({ result: "only line" })} />);

    expect(badgesText()).toBe('tool.lineBadge.lines[{"count":1}]');
  });

  it("renders no file contents and no preview when the read failed", () => {
    render(<ReadFileCard content={createContent({ status: "error" })} />);

    expect(screen.queryByTestId("badges")).toBeNull();
    expect(screen.queryByTestId("summary-action")).toBeNull();
    expect(screen.queryByTestId("block-Output")).toBeNull();
    expect(screen.queryByTestId("file-attachment")).toBeNull();
  });

  it("still names the file in the title of a failed read", () => {
    render(<ReadFileCard content={createContent({ status: "error" })} />);

    expect(titleText()).toBe('tool.readFile[{"file":"SHORT(config.ts)"}]');
  });

  it("offers the file preview next to a successful read", () => {
    render(<ReadFileCard content={createContent()} />);

    expect(screen.getByTestId("file-preview-link")).toBeInTheDocument();
    expect(screen.getByTestId("file-attachment")).toBeInTheDocument();
  });

  it("renders no output block when the result is not text", () => {
    render(<ReadFileCard content={createContent({ result: { lines: 3 } })} />);

    expect(screen.queryByTestId("block-Output")).toBeNull();
  });
});
