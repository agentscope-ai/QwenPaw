// @vitest-environment jsdom
/**
 * Contract tests for EditFileCard.
 *
 * The card is the user's only view of an edit: the file name in the title, the
 * added/removed line counts in the badges, and the before/after diff lines in
 * the body. All three are derived here from the tool params, so all three are
 * pinned. The formatter (shortFileName) and the preview components have their
 * own tests and are mocked to identifiable placeholders.
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
  FileAttachmentPreview: () => <div data-testid="file-attachment" />,
  FilePreviewLink: () => <button data-testid="file-preview-link" />,
}));

vi.mock("../shared/utils", () => ({
  shortFileName: (path: unknown) => (path ? `SHORT(${path})` : ""),
}));

import EditFileCard from "./EditFileCard";

const NO_PARAMS = undefined as unknown as Record<string, unknown>;

const createContent = (
  overrides: Partial<ToolCallContent> = {},
): ToolCallContent => ({
  type: "tool_call",
  id: "edit-1",
  name: "edit_file",
  status: "done",
  params: {
    file_path: "src/app.ts",
    old_text: "before",
    new_text: "after",
  },
  ...overrides,
});

const titleText = () => screen.getByTestId("card-title").textContent;
const badgesText = () => screen.queryByTestId("badges")?.textContent;

describe("EditFileCard", () => {
  it("names the edited file in the title", () => {
    render(<EditFileCard content={createContent()} />);

    expect(titleText()).toBe('tool.editFile[{"file":"SHORT(src/app.ts)"}]');
  });

  it("falls back to the path param when file_path is absent", () => {
    render(
      <EditFileCard
        content={createContent({
          params: { path: "notes/todo.md", old_text: "a", new_text: "b" },
        })}
      />,
    );

    expect(titleText()).toBe('tool.editFile[{"file":"SHORT(notes/todo.md)"}]');
  });

  it("uses the default title when the call names no file", () => {
    render(
      <EditFileCard
        content={createContent({ params: { old_text: "a", new_text: "b" } })}
      />,
    );

    expect(titleText()).toBe("tool.editFileDefault");
  });

  it("uses the default title when the call carries no params", () => {
    render(<EditFileCard content={createContent({ params: NO_PARAMS })} />);

    expect(titleText()).toBe("tool.editFileDefault");
  });

  it("counts the added and removed lines in the badges", () => {
    render(
      <EditFileCard
        content={createContent({
          params: {
            file_path: "src/app.ts",
            old_text: "old one\nold two",
            new_text: "new one\nnew two\nnew three",
          },
        })}
      />,
    );

    expect(badgesText()).toBe(
      'tool.lineBadge.addLines[{"count":3}]tool.lineBadge.delLines[{"count":2}]',
    );
  });

  it("counts an empty side as a single line", () => {
    render(
      <EditFileCard
        content={createContent({
          params: { file_path: "src/app.ts", old_text: "", new_text: "added" },
        })}
      />,
    );

    expect(badgesText()).toBe(
      'tool.lineBadge.addLines[{"count":1}]tool.lineBadge.delLines[{"count":1}]',
    );
  });

  it("shows the removed lines marked with a minus and the added ones with a plus", () => {
    render(
      <EditFileCard
        content={createContent({
          params: {
            file_path: "src/app.ts",
            old_text: "old one",
            new_text: "new one",
          },
        })}
      />,
    );

    const body = screen.getByTestId("card-body").textContent ?? "";
    expect(body).toContain("- old one");
    expect(body).toContain("+ new one");
  });

  it("shows every line of a multi-line edit", () => {
    render(
      <EditFileCard
        content={createContent({
          params: {
            file_path: "src/app.ts",
            old_text: "old one\nold two",
            new_text: "new one\nnew two",
          },
        })}
      />,
    );

    const body = screen.getByTestId("card-body").textContent ?? "";
    expect(body).toContain("- old one");
    expect(body).toContain("- old two");
    expect(body).toContain("+ new one");
    expect(body).toContain("+ new two");
  });

  it("renders an edit with no declared text as one empty removed and one empty added line", () => {
    render(
      <EditFileCard
        content={createContent({ params: { file_path: "a.ts" } })}
      />,
    );

    const body = screen.getByTestId("card-body").textContent ?? "";
    expect(body).toContain("- ");
    expect(body).toContain("+ ");
  });

  it("hides the badges while the edit is still streaming in", () => {
    render(
      <EditFileCard
        content={createContent({ status: "calling" })}
        isStreaming
      />,
    );

    expect(screen.queryByTestId("badges")).toBeNull();
  });

  it("shows the badges once the streamed edit has settled", () => {
    render(<EditFileCard content={createContent({ status: "calling" })} />);

    expect(badgesText()).toContain("tool.lineBadge.addLines");
  });

  it("shows the badges for a finished edit even while the message streams", () => {
    render(<EditFileCard content={createContent()} isStreaming />);

    expect(badgesText()).toContain("tool.lineBadge.addLines");
  });

  it("renders no diff and no preview when the edit failed", () => {
    render(<EditFileCard content={createContent({ status: "error" })} />);

    expect(screen.queryByTestId("badges")).toBeNull();
    expect(screen.queryByTestId("summary-action")).toBeNull();
    expect(screen.getByTestId("card-body").textContent).toBe("");
    expect(screen.queryByText(/[-+] /)).toBeNull();
  });

  it("still names the file in the title of a failed edit", () => {
    render(<EditFileCard content={createContent({ status: "error" })} />);

    expect(titleText()).toBe('tool.editFile[{"file":"SHORT(src/app.ts)"}]');
  });

  it("offers the file preview next to a successful edit", () => {
    render(<EditFileCard content={createContent()} />);

    expect(screen.getByTestId("file-preview-link")).toBeInTheDocument();
    expect(screen.getByTestId("file-attachment")).toBeInTheDocument();
  });
});
