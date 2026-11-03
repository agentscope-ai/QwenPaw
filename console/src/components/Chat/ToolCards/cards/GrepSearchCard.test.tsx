// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: { count?: number }) =>
      key === "tool.lineBadge.matches" ? `${options?.count} matches` : key,
  }),
}));

vi.mock("../shared", () => ({
  ToolCardShell: ({
    badges,
    children,
  }: {
    badges?: React.ReactNode;
    children?: React.ReactNode;
  }) => (
    <div>
      {badges}
      {children}
    </div>
  ),
  DefaultBlock: ({ content }: { content: string }) => <pre>{content}</pre>,
}));

vi.mock("../shared/utils", () => ({
  countLines: (text: unknown) =>
    typeof text === "string" && text ? text.split("\n").length : 0,
  stringifyResult: (result: unknown) =>
    typeof result === "string" ? result : "",
}));

import GrepSearchCard from "./GrepSearchCard";

const createContent = (result: string) => ({
  type: "tool_call" as const,
  id: "grep-1",
  name: "grep_search",
  status: "done" as const,
  params: { pattern: "needle" },
  result,
});

describe("GrepSearchCard", () => {
  it("does not show a match badge for the no-match result message", () => {
    render(
      <GrepSearchCard
        content={createContent("No matches found for pattern: needle")}
      />,
    );

    expect(screen.queryByText("1 matches")).not.toBeInTheDocument();
    expect(
      screen.getByText("No matches found for pattern: needle"),
    ).toBeInTheDocument();
  });

  it("shows the line count for actual matches", () => {
    render(
      <GrepSearchCard content={createContent("src/example.ts:1: needle")} />,
    );

    expect(screen.getByText("1 matches")).toBeInTheDocument();
  });
});
