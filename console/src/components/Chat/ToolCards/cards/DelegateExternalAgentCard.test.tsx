// @vitest-environment jsdom
/**
 * Contract tests for DelegateExternalAgentCard.
 *
 * This card reports work handed to an external runner. Two things are pinned:
 * the runner name reaching the title, and the fallback title when the call
 * carries no runner at all. The card is otherwise the same shape as
 * ChatWithAgentCard, so its output-block contract is pinned too: only text
 * results get a block, anything else renders an empty body.
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

import DelegateExternalAgentCard from "./DelegateExternalAgentCard";

const NO_PARAMS = undefined as unknown as Record<string, unknown>;

const createContent = (
  overrides: Partial<ToolCallContent> = {},
): ToolCallContent => ({
  type: "tool_call",
  id: "delegate-1",
  name: "delegate_external_agent",
  status: "done",
  params: { runner: "claude-code" },
  result: "task finished",
  ...overrides,
});

const titleText = () => screen.getByTestId("card-title").textContent;

describe("DelegateExternalAgentCard", () => {
  it("names the external runner in the title", () => {
    render(<DelegateExternalAgentCard content={createContent()} />);

    expect(titleText()).toBe(
      'tool.delegateExternalAgent[{"runner":"claude-code"}]',
    );
  });

  it("uses the default title when no runner was given", () => {
    render(
      <DelegateExternalAgentCard content={createContent({ params: {} })} />,
    );

    expect(titleText()).toBe("tool.delegateExternalAgentDefault");
  });

  it("uses the default title when the call carries no params", () => {
    render(
      <DelegateExternalAgentCard
        content={createContent({ params: NO_PARAMS })}
      />,
    );

    expect(titleText()).toBe("tool.delegateExternalAgentDefault");
  });

  it("shows the runner output in the output block", () => {
    render(<DelegateExternalAgentCard content={createContent()} />);

    expect(screen.getByTestId("block-Output").textContent).toBe(
      "task finished",
    );
  });

  it("renders no output block when the runner returned nothing", () => {
    render(
      <DelegateExternalAgentCard content={createContent({ result: "" })} />,
    );

    expect(screen.queryByTestId("block-Output")).toBeNull();
    expect(screen.getByTestId("card-body").textContent).toBe("");
  });

  it("renders no output block when the result is not text", () => {
    render(
      <DelegateExternalAgentCard
        content={createContent({ result: { exit: 0 } })}
      />,
    );

    expect(screen.queryByTestId("block-Output")).toBeNull();
  });

  it("keeps naming the runner while the delegation is still running", () => {
    render(
      <DelegateExternalAgentCard
        content={createContent({ status: "calling", result: "" })}
        isStreaming
      />,
    );

    expect(titleText()).toBe(
      'tool.delegateExternalAgent[{"runner":"claude-code"}]',
    );
    expect(screen.queryByTestId("block-Output")).toBeNull();
  });
});
