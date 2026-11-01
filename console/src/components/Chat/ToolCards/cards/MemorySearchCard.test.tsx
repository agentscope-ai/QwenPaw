// @vitest-environment jsdom
/**
 * Contract tests for MemorySearchCard.
 *
 * The card turns memory_search params into the one-line title the user reads
 * in the collapsed card (query + limit/min_score suffix), and turns the result
 * into the expandable output block. Both mappings are the card's own contract:
 * the formatter itself is mocked here because it has its own test file.
 *
 * There was no test file for this card before this one.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: { query?: string }) =>
      key === "tool.memorySearch" ? `search ${options?.query}` : key,
  }),
}));

vi.mock("../shared", () => ({
  ToolCardShell: ({
    title,
    children,
  }: {
    title?: string;
    children?: React.ReactNode;
  }) => (
    <div>
      <span data-testid="card-title">{title}</span>
      {children}
    </div>
  ),
  DefaultBlock: ({ content }: { content: string }) => (
    <pre data-testid="block">{content}</pre>
  ),
}));

vi.mock("../shared/utils", () => ({
  formatMemorySearch: (raw: string) => `FORMATTED(${raw})`,
}));

import MemorySearchCard from "./MemorySearchCard";

const createContent = (overrides: Record<string, unknown> = {}) =>
  ({
    type: "tool_call",
    id: "mem-1",
    name: "memory_search",
    status: "done",
    params: { query: "cabin pressure" },
    ...overrides,
  }) as never;

const title = () => screen.getByTestId("card-title");

describe("MemorySearchCard", () => {
  it("puts the query into the title", () => {
    render(<MemorySearchCard content={createContent()} />);

    expect(title()).toHaveTextContent("search cabin pressure");
  });

  it("uses the default title when no query param is given", () => {
    render(<MemorySearchCard content={createContent({ params: {} })} />);

    expect(title()).toHaveTextContent("tool.memorySearchDefault");
  });

  it("reads the query from the text param when there is no query param", () => {
    render(
      <MemorySearchCard
        content={createContent({ params: { text: "via text" } })}
      />,
    );

    expect(title()).toHaveTextContent("search via text");
  });

  it("survives a tool call that carried no params at all", () => {
    render(<MemorySearchCard content={createContent({ params: undefined })} />);

    expect(title()).toHaveTextContent("tool.memorySearchDefault");
  });

  it("shortens a query longer than 20 characters", () => {
    render(
      <MemorySearchCard
        content={createContent({ params: { query: "a".repeat(21) } })}
      />,
    );

    expect(title()).toHaveTextContent("search " + "a".repeat(20) + "\u2026");
  });

  it("keeps a query of exactly 20 characters whole", () => {
    render(
      <MemorySearchCard
        content={createContent({ params: { query: "b".repeat(20) } })}
      />,
    );

    expect(title()).toHaveTextContent("search " + "b".repeat(20));
  });

  it("appends the limit to the title", () => {
    render(
      <MemorySearchCard
        content={createContent({ params: { query: "q", limit: 5 } })}
      />,
    );

    expect(title()).toHaveTextContent("search q \u00b7 limit=5");
  });

  it("reads the limit from max_results when limit is absent", () => {
    render(
      <MemorySearchCard
        content={createContent({ params: { query: "q", max_results: 8 } })}
      />,
    );

    expect(title()).toHaveTextContent("search q \u00b7 limit=8");
  });

  it("shows a limit of zero rather than dropping it", () => {
    render(
      <MemorySearchCard
        content={createContent({ params: { query: "q", limit: 0 } })}
      />,
    );

    expect(title()).toHaveTextContent("limit=0");
  });

  it("appends min_score to the title", () => {
    render(
      <MemorySearchCard
        content={createContent({ params: { query: "q", min_score: 0.5 } })}
      />,
    );

    expect(title()).toHaveTextContent("search q \u00b7 min_score=0.5");
  });

  it("appends both limit and min_score in that order", () => {
    render(
      <MemorySearchCard
        content={createContent({
          params: { query: "q", limit: 3, min_score: 1 },
        })}
      />,
    );

    expect(title()).toHaveTextContent("search q \u00b7 limit=3 min_score=1");
  });

  it("drops a non-numeric limit instead of showing NaN", () => {
    render(
      <MemorySearchCard
        content={createContent({ params: { query: "q", limit: "many" } })}
      />,
    );

    expect(title()).toHaveTextContent("search q");
    expect(title()).not.toHaveTextContent("NaN");
  });

  it("renders no output block for a failed call", () => {
    render(
      <MemorySearchCard
        content={createContent({ status: "error", result: "boom" })}
      />,
    );

    expect(title()).toHaveTextContent("search cabin pressure");
    expect(screen.queryByTestId("block")).toBeNull();
  });

  it("passes a string result straight to the formatter", () => {
    render(
      <MemorySearchCard content={createContent({ result: "raw text" })} />,
    );

    expect(screen.getByTestId("block")).toHaveTextContent(
      "FORMATTED(raw text)",
    );
  });

  it("serializes a non-string result before formatting it", () => {
    render(
      <MemorySearchCard content={createContent({ result: { hit: 1 } })} />,
    );

    expect(screen.getByTestId("block")).toHaveTextContent(
      'FORMATTED({"hit":1})',
    );
  });

  it("renders no output block when the call returned nothing", () => {
    render(<MemorySearchCard content={createContent({ result: undefined })} />);

    expect(screen.queryByTestId("block")).toBeNull();
  });

  it("renders no output block when the formatter produced nothing", () => {
    render(<MemorySearchCard content={createContent({ result: "" })} />);

    expect(screen.queryByTestId("block")).toBeNull();
  });
});
