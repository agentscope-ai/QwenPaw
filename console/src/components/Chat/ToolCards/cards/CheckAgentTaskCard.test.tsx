// @vitest-environment jsdom
/**
 * Contract tests for CheckAgentTaskCard.
 *
 * The card has to stay readable when the caller only knows part of the target:
 * the tool accepts either agent_id or to_agent, and a task id may be missing
 * entirely. The three resulting titles plus the output block are the card's own
 * contract and are pinned here.
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
  DefaultBlock: ({ content }: { content?: string }) => (
    <pre data-testid="block-Output">{content}</pre>
  ),
}));

vi.mock("../shared/utils", () => ({
  stringifyResult: (result: unknown) =>
    typeof result === "string" ? result : "",
}));

import CheckAgentTaskCard from "./CheckAgentTaskCard";

const NO_PARAMS = undefined as unknown as Record<string, unknown>;

const createContent = (
  overrides: Partial<ToolCallContent> = {},
): ToolCallContent => ({
  type: "tool_call",
  id: "check-1",
  name: "check_agent_task",
  status: "done",
  params: {},
  ...overrides,
});

const titleText = () => screen.getByTestId("card-title").textContent;

describe("CheckAgentTaskCard", () => {
  it("names both the agent and the task when the call gives them", () => {
    render(
      <CheckAgentTaskCard
        content={createContent({
          params: { agent_id: "qa-agent", task_id: "task-42" },
        })}
      />,
    );

    expect(titleText()).toBe(
      'tool.checkAgentTask[{"agent":"qa-agent","taskId":"task-42"}]',
    );
  });

  it("accepts to_agent as the agent name", () => {
    render(
      <CheckAgentTaskCard
        content={createContent({
          params: { to_agent: "other-agent", task_id: "task-7" },
        })}
      />,
    );

    expect(titleText()).toBe(
      'tool.checkAgentTask[{"agent":"other-agent","taskId":"task-7"}]',
    );
  });

  it("prefers agent_id over to_agent when both are present", () => {
    render(
      <CheckAgentTaskCard
        content={createContent({
          params: { agent_id: "primary", to_agent: "secondary" },
        })}
      />,
    );

    expect(titleText()).toBe('tool.checkAgentTaskAgent[{"agent":"primary"}]');
  });

  it("drops the task id from the title when the call gives none", () => {
    render(
      <CheckAgentTaskCard
        content={createContent({ params: { agent_id: "qa-agent" } })}
      />,
    );

    expect(titleText()).toBe('tool.checkAgentTaskAgent[{"agent":"qa-agent"}]');
  });

  it("uses the default title when the call names no agent", () => {
    render(
      <CheckAgentTaskCard
        content={createContent({ params: { task_id: "task-42" } })}
      />,
    );

    expect(titleText()).toBe("tool.checkAgentTaskDefault");
  });

  it("uses the default title when the call carries no params", () => {
    render(
      <CheckAgentTaskCard content={createContent({ params: NO_PARAMS })} />,
    );

    expect(titleText()).toBe("tool.checkAgentTaskDefault");
  });

  it("uses the default title when both ids are empty strings", () => {
    render(
      <CheckAgentTaskCard
        content={createContent({ params: { agent_id: "", task_id: "" } })}
      />,
    );

    expect(titleText()).toBe("tool.checkAgentTaskDefault");
  });

  it("shows the polled status as the output block", () => {
    render(
      <CheckAgentTaskCard
        content={createContent({
          params: { task_id: "task-42" },
          result: "STATUS=finished",
        })}
      />,
    );

    expect(screen.getByTestId("block-Output").textContent).toBe(
      "STATUS=finished",
    );
  });

  it("renders no output block while the poll has returned nothing", () => {
    render(
      <CheckAgentTaskCard
        content={createContent({ status: "calling", result: undefined })}
      />,
    );

    expect(screen.queryByTestId("block-Output")).toBeNull();
  });

  it("renders no output block when the result is not text", () => {
    render(
      <CheckAgentTaskCard
        content={createContent({ result: { status: "finished" } })}
      />,
    );

    expect(screen.queryByTestId("block-Output")).toBeNull();
  });

  it("keeps the title even when the poll failed", () => {
    render(
      <CheckAgentTaskCard
        content={createContent({
          status: "error",
          params: { agent_id: "qa-agent", task_id: "task-42" },
        })}
      />,
    );

    expect(titleText()).toBe(
      'tool.checkAgentTask[{"agent":"qa-agent","taskId":"task-42"}]',
    );
  });
});
