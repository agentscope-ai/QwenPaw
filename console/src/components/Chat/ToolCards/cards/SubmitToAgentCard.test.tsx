// @vitest-environment jsdom
/**
 * Contract tests for SubmitToAgentCard.
 *
 * The card owns two pieces of user-visible text: the summary title (which agent
 * is receiving how much of the task) and the inline result line (whether the
 * submission handed back a task id). Both are derived inside this component, so
 * both are pinned here for every input shape the tool can produce.
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
    inlineResult,
  }: {
    title?: string;
    inlineResult?: string | null;
  }) => (
    <div>
      <span data-testid="card-title">{title}</span>
      {inlineResult ? <span data-testid="inline">{inlineResult}</span> : null}
    </div>
  ),
}));

import SubmitToAgentCard from "./SubmitToAgentCard";

const NO_PARAMS = undefined as unknown as Record<string, unknown>;

const createContent = (
  overrides: Partial<ToolCallContent> = {},
): ToolCallContent => ({
  type: "tool_call",
  id: "submit-1",
  name: "submit_to_agent",
  status: "done",
  params: {},
  ...overrides,
});

const titleText = () => screen.getByTestId("card-title").textContent;
const inline = () => screen.queryByTestId("inline");

describe("SubmitToAgentCard", () => {
  it("names the receiving agent and previews the task in the title", () => {
    render(
      <SubmitToAgentCard
        content={createContent({
          params: { to_agent: "qa-agent", text: "run the suite" },
        })}
      />,
    );

    expect(titleText()).toBe(
      'tool.submitToAgent[{"agent":"qa-agent","task":" run the suite"}]',
    );
  });

  it("keeps a task of exactly 20 characters whole", () => {
    const text = "c".repeat(20);
    render(
      <SubmitToAgentCard
        content={createContent({ params: { to_agent: "qa", text } })}
      />,
    );

    expect(titleText()).toBe(
      `tool.submitToAgent[{"agent":"qa","task":" ${text}"}]`,
    );
  });

  it("truncates a task longer than 20 characters with an ellipsis", () => {
    const text = "d".repeat(21);
    render(
      <SubmitToAgentCard
        content={createContent({ params: { to_agent: "qa", text } })}
      />,
    );

    expect(titleText()).toBe(
      `tool.submitToAgent[{"agent":"qa","task":" ${"d".repeat(20)}\u2026"}]`,
    );
  });

  it("leaves the task part empty when no task text was submitted", () => {
    render(
      <SubmitToAgentCard
        content={createContent({ params: { to_agent: "qa" } })}
      />,
    );

    expect(titleText()).toBe('tool.submitToAgent[{"agent":"qa","task":""}]');
  });

  it("falls back to the default title when no agent was given", () => {
    render(
      <SubmitToAgentCard
        content={createContent({ params: { text: "orphan task" } })}
      />,
    );

    expect(titleText()).toBe("tool.submitToAgentDefault");
  });

  it("falls back to the default title when the call carries no params", () => {
    render(
      <SubmitToAgentCard content={createContent({ params: NO_PARAMS })} />,
    );

    expect(titleText()).toBe("tool.submitToAgentDefault");
  });

  it("surfaces the task id the submission handed back", () => {
    render(
      <SubmitToAgentCard
        content={createContent({ result: "queued [TASK_ID: task-abc123] ok" })}
      />,
    );

    expect(inline()).toHaveTextContent(
      'tool.inlineResult.taskId[{"id":"task-abc123"}]',
    );
  });

  it("tolerates extra whitespace after the task id marker", () => {
    render(
      <SubmitToAgentCard
        content={createContent({ result: "[TASK_ID:    spaced-id]" })}
      />,
    );

    expect(inline()).toHaveTextContent(
      'tool.inlineResult.taskId[{"id":"spaced-id"}]',
    );
  });

  it("reports a plain submission when the result carries no task id", () => {
    render(
      <SubmitToAgentCard
        content={createContent({ result: "submitted to the other agent" })}
      />,
    );

    expect(inline()).toHaveTextContent("tool.inlineResult.submitted");
  });

  it("shows no inline result while the call is still running", () => {
    render(
      <SubmitToAgentCard
        content={createContent({
          status: "calling",
          result: "[TASK_ID: early]",
        })}
      />,
    );

    expect(inline()).toBeNull();
  });

  it("shows no inline result when the call failed", () => {
    render(
      <SubmitToAgentCard
        content={createContent({
          status: "error",
          result: "[TASK_ID: never]",
        })}
      />,
    );

    expect(inline()).toBeNull();
  });

  it("shows no inline result when the call finished without a result", () => {
    render(
      <SubmitToAgentCard content={createContent({ result: undefined })} />,
    );

    expect(inline()).toBeNull();
  });

  it("shows no inline result when the result is an empty string", () => {
    render(<SubmitToAgentCard content={createContent({ result: "" })} />);

    expect(inline()).toBeNull();
  });

  it("shows no inline result when the result is not text", () => {
    render(
      <SubmitToAgentCard
        content={createContent({ result: { taskId: "task-1" } })}
      />,
    );

    expect(inline()).toBeNull();
  });
});
