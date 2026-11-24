// @vitest-environment jsdom
/**
 * Contract tests for GlobSearchCard.
 *
 * GlobSearchCard is the file-finding twin of GrepSearchCard: it puts the search
 * pattern in the title and counts the matched files in a badge once the search
 * finished. Unlike GrepSearch it has no "no matches found" special case: a
 * search that returns an empty result simply gets no badge, which is pinned
 * here so the two cards' different behaviour stays deliberate rather than a
 * copy-paste accident.
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
    children,
  }: {
    title?: string;
    badges?: React.ReactNode;
    children?: React.ReactNode;
  }) => (
    <div>
      <span data-testid="card-title">{title}</span>
      {badges ? <div data-testid="badges">{badges}</div> : null}
      <div data-testid="card-body">{children}</div>
    </div>
  ),
  DefaultBlock: ({ content }: { content?: string }) => (
    <pre data-testid="block-Output">{content}</pre>
  ),
}));

vi.mock("../shared/utils", () => ({
  countLines: (text: unknown) =>
    typeof text === "string" && text ? text.split("\n").length : 0,
  stringifyResult: (result: unknown) =>
    typeof result === "string" ? result : "",
}));

import GlobSearchCard from "./GlobSearchCard";

const NO_PARAMS = undefined as unknown as Record<string, unknown>;

const createContent = (
  overrides: Partial<ToolCallContent> = {},
): ToolCallContent => ({
  type: "tool_call",
  id: "glob-1",
  name: "glob_search",
  status: "done",
  params: { pattern: "**/*.ts" },
  result: "a.ts\nb.ts",
  ...overrides,
});

const titleText = () => screen.getByTestId("card-title").textContent;
const badgesText = () => screen.queryByTestId("badges")?.textContent;

describe("GlobSearchCard", () => {
  it("puts the glob pattern in the title", () => {
    render(<GlobSearchCard content={createContent()} />);

    expect(titleText()).toBe('tool.globSearch[{"pattern":"**/*.ts"}]');
  });

  it("uses the default title when the call gives no pattern", () => {
    render(<GlobSearchCard content={createContent({ params: {} })} />);

    expect(titleText()).toBe("tool.globSearchDefault");
  });

  it("uses the default title when the call carries no params", () => {
    render(<GlobSearchCard content={createContent({ params: NO_PARAMS })} />);

    expect(titleText()).toBe("tool.globSearchDefault");
  });

  it("counts the matched files in the badge", () => {
    render(<GlobSearchCard content={createContent()} />);

    expect(badgesText()).toBe('tool.lineBadge.files[{"count":2}]');
  });

  it("shows the matched file list in the output block", () => {
    render(<GlobSearchCard content={createContent()} />);

    expect(screen.getByTestId("block-Output").textContent).toBe("a.ts\nb.ts");
  });

  it("shows no badge when the search matched nothing", () => {
    render(<GlobSearchCard content={createContent({ result: "" })} />);

    expect(screen.queryByTestId("badges")).toBeNull();
    expect(screen.queryByTestId("block-Output")).toBeNull();
  });

  it("counts a single match as one file", () => {
    render(<GlobSearchCard content={createContent({ result: "only.ts" })} />);

    expect(badgesText()).toBe('tool.lineBadge.files[{"count":1}]');
  });

  it("shows no badge while the search is still running", () => {
    render(
      <GlobSearchCard
        content={createContent({ status: "calling", result: "" })}
      />,
    );

    expect(screen.queryByTestId("badges")).toBeNull();
  });

  it("renders no match list when the search failed", () => {
    render(<GlobSearchCard content={createContent({ status: "error" })} />);

    expect(screen.queryByTestId("badges")).toBeNull();
    expect(screen.queryByTestId("block-Output")).toBeNull();
    expect(screen.getByTestId("card-body").textContent).toBe("");
  });

  it("still names the pattern in the title of a failed search", () => {
    render(<GlobSearchCard content={createContent({ status: "error" })} />);

    expect(titleText()).toBe('tool.globSearch[{"pattern":"**/*.ts"}]');
  });

  it("renders no output block when the result is not text", () => {
    render(
      <GlobSearchCard content={createContent({ result: { files: [] } })} />,
    );

    expect(screen.queryByTestId("block-Output")).toBeNull();
  });
});
