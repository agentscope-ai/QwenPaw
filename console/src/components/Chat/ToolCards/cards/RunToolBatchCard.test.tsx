/**
 * Tests for RunToolBatchCard memoization and media extraction.
 *
 * The card walks the whole result tree and runs whole-text regexes, so it
 * must be memoized: identical props must not trigger a re-render, and the
 * derived media/output values must be cached per result reference.
 */
// @vitest-environment jsdom
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

const shellRenderSpy = vi.hoisted(() => vi.fn());

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock("../shared", () => ({
  ToolCardShell: ({
    title,
    children,
  }: {
    title: string;
    children?: React.ReactNode;
  }) => {
    shellRenderSpy();
    return (
      <div data-testid="shell">
        {title}
        {children}
      </div>
    );
  },
  DefaultBlock: ({ title, content }: { title: string; content: string }) => (
    <div data-testid={`block-${title}`}>{content}</div>
  ),
  MediaPreview: ({ media }: { media: { url: string } }) => (
    <div data-testid="media">{media.url}</div>
  ),
}));

import RunToolBatchCard from "./RunToolBatchCard";
import type { ToolCallContent } from "../shared/types";

function makeContent(result: unknown): ToolCallContent {
  return {
    type: "tool_call",
    id: "call-1",
    name: "run_tool_batch",
    params: { file_path: "flow.json" },
    result,
    status: "done",
  };
}

describe("RunToolBatchCard", () => {
  it("renders media previews and text output from the result blocks", () => {
    const content = makeContent([
      { type: "image", url: "/api/files/preview/out.png", name: "out.png" },
      { type: "text", text: "batch finished" },
    ]);

    render(<RunToolBatchCard content={content} />);

    expect(screen.getByTestId("media")).toBeInTheDocument();
    expect(screen.getByTestId("block-Output")).toHaveTextContent(
      "batch finished",
    );
  });

  it("skips re-rendering when props are unchanged (React.memo)", () => {
    const content = makeContent([{ type: "text", text: "done" }]);

    const { rerender } = render(<RunToolBatchCard content={content} />);
    const rendersAfterMount = shellRenderSpy.mock.calls.length;

    rerender(<RunToolBatchCard content={content} />);
    expect(shellRenderSpy.mock.calls.length).toBe(rendersAfterMount);

    // A new content reference must re-render.
    rerender(
      <RunToolBatchCard
        content={makeContent([{ type: "text", text: "changed" }])}
      />,
    );
    expect(shellRenderSpy.mock.calls.length).toBeGreaterThan(rendersAfterMount);
  });
});
