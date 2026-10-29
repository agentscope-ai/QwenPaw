// @vitest-environment jsdom
/**
 * Contract tests for TokenUsageCard.
 *
 * The card takes no params at all, so its whole contract is the title plus the
 * output block decision: a textual usage report gets a block, everything else
 * renders an empty body. The empty-body case is the one worth pinning because a
 * usage query that returned nothing must not show a blank strip.
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
    children,
  }: {
    title?: string;
    children?: React.ReactNode;
  }) => (
    <div>
      <span data-testid="card-title">{title}</span>
      <div data-testid="card-body">{children}</div>
    </div>
  ),
  DefaultBlock: ({ title, content }: { title?: string; content?: string }) => (
    <pre data-testid={`block-${title}`}>{content}</pre>
  ),
}));

vi.mock("../shared/utils", () => ({
  stringifyResult: (result: unknown) =>
    typeof result === "string" ? result : "",
}));

import TokenUsageCard from "./TokenUsageCard";

const createContent = (
  overrides: Partial<ToolCallContent> = {},
): ToolCallContent => ({
  type: "tool_call",
  id: "usage-1",
  name: "get_token_usage",
  status: "done",
  params: { days: 30 },
  result: "total: 12345 tokens",
  ...overrides,
});

describe("TokenUsageCard", () => {
  it("titles the card with the token-usage label", () => {
    render(<TokenUsageCard content={createContent()} />);

    expect(screen.getByTestId("card-title").textContent).toBe(
      "tool.getTokenUsage",
    );
  });

  it("shows the usage report in the output block", () => {
    render(<TokenUsageCard content={createContent()} />);

    expect(screen.getByTestId("block-Output").textContent).toBe(
      "total: 12345 tokens",
    );
  });

  it("renders no output block when the query returned no text", () => {
    render(<TokenUsageCard content={createContent({ result: "" })} />);

    expect(screen.queryByTestId("block-Output")).toBeNull();
    expect(screen.getByTestId("card-body").textContent).toBe("");
  });

  it("renders no output block when the result is not text", () => {
    render(
      <TokenUsageCard content={createContent({ result: { days: 30 } })} />,
    );

    expect(screen.queryByTestId("block-Output")).toBeNull();
  });

  it("titles the card the same way while the query is running", () => {
    render(
      <TokenUsageCard
        content={createContent({ status: "calling", result: "" })}
        isStreaming
      />,
    );

    expect(screen.getByTestId("card-title").textContent).toBe(
      "tool.getTokenUsage",
    );
    expect(screen.queryByTestId("block-Output")).toBeNull();
  });
});
