// @vitest-environment jsdom
/**
 * Contract tests for ListAgentsCard.
 *
 * This card is the only one in the set that normalises its result before
 * formatting: a string result is handed to the shared formatter as-is, any
 * other non-null result is JSON stringified first, and a missing result yields
 * an empty string that skips formatting entirely. Those three arms are the
 * whole logic of the card, so each one is pinned separately, together with the
 * fact that an empty normalised result renders no output block.
 *
 * There was no test file for this card before this one.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ToolCallContent } from "../shared/types";

const formattedCalls: Array<{ raw: unknown; tName: string }> = [];

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
  formatAgentList: (raw: unknown, t: (k: string) => string) => {
    formattedCalls.push({ raw, tName: typeof t });
    return `formatted:${String(raw)}`;
  },
}));

import ListAgentsCard from "./ListAgentsCard";

const createContent = (
  overrides: Partial<ToolCallContent> = {},
): ToolCallContent => ({
  type: "tool_call",
  id: "agents-1",
  name: "list_agents",
  status: "done",
  params: {},
  result: '[{"id":"qpqat-envoy"}]',
  ...overrides,
});

const titleText = () => screen.getByTestId("card-title").textContent;

describe("ListAgentsCard", () => {
  it("titles the card with the list-agents label", () => {
    render(<ListAgentsCard content={createContent()} />);

    expect(titleText()).toBe("tool.listAgents");
  });

  it("formats a string result without re-encoding it", () => {
    render(<ListAgentsCard content={createContent()} />);

    expect(screen.getByTestId("block-Output").textContent).toBe(
      'formatted:[{"id":"qpqat-envoy"}]',
    );
  });

  it("json stringifies an object result before formatting", () => {
    render(
      <ListAgentsCard
        content={createContent({ result: { agents: [{ id: "a" }] } })}
      />,
    );

    expect(screen.getByTestId("block-Output").textContent).toBe(
      'formatted:{"agents":[{"id":"a"}]}',
    );
  });

  it("json stringifies an array result before formatting", () => {
    render(<ListAgentsCard content={createContent({ result: [1, 2] })} />);

    expect(screen.getByTestId("block-Output").textContent).toBe(
      "formatted:[1,2]",
    );
  });

  it("renders no output block when the call produced no result", () => {
    render(<ListAgentsCard content={createContent({ result: null })} />);

    expect(screen.queryByTestId("block-Output")).toBeNull();
    expect(screen.getByTestId("card-body").textContent).toBe("");
  });

  it("renders no output block when the result field is missing", () => {
    render(<ListAgentsCard content={createContent({ result: undefined })} />);

    expect(screen.queryByTestId("block-Output")).toBeNull();
  });

  it("renders no output block for an empty string result", () => {
    render(<ListAgentsCard content={createContent({ result: "" })} />);

    expect(screen.queryByTestId("block-Output")).toBeNull();
  });

  it("hands the translation function to the formatter", () => {
    render(<ListAgentsCard content={createContent()} />);

    expect(formattedCalls.every((c) => c.tName === "function")).toBe(true);
  });

  it("still titles the card while the call is running", () => {
    render(
      <ListAgentsCard
        content={createContent({ status: "calling", result: null })}
        isStreaming
      />,
    );

    expect(titleText()).toBe("tool.listAgents");
    expect(screen.queryByTestId("block-Output")).toBeNull();
  });
});
