// @vitest-environment jsdom
/**
 * Contract tests for ShellCard.
 *
 * Two behaviours are worth pinning. First, the intent supplied by the model
 * is the card title, with the command as its fallback. Second, the failed-call
 * shape deliberately renders no output block because the error surface belongs
 * to the shell and stale stdout would be misleading.
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

import ShellCard from "./ShellCard";

const NO_PARAMS = undefined as unknown as Record<string, unknown>;

const createContent = (
  overrides: Partial<ToolCallContent> = {},
): ToolCallContent => ({
  type: "tool_call",
  id: "shell-1",
  name: "execute_shell_command",
  status: "done",
  params: { command: "ls -la", title: "Inspect workspace files" },
  result: "total 0",
  ...overrides,
});

const titleText = () => screen.getByTestId("card-title").textContent;

describe("ShellCard", () => {
  it("puts the shell intent in the title", () => {
    render(<ShellCard content={createContent()} />);

    expect(titleText()).toBe(
      'tool.shellCompleted[{"command":"Inspect workspace files"}]',
    );
  });

  it("falls back to the command when no intent was given", () => {
    render(
      <ShellCard content={createContent({ params: { command: "pwd" } })} />,
    );

    expect(titleText()).toBe('tool.shellCompleted[{"command":"pwd"}]');
  });

  it("accepts the command under the cmd param name too", () => {
    render(<ShellCard content={createContent({ params: { cmd: "pwd" } })} />);

    expect(titleText()).toBe('tool.shellCompleted[{"command":"pwd"}]');
  });

  it("prefers command over cmd when both are present", () => {
    render(
      <ShellCard
        content={createContent({ params: { command: "ls", cmd: "pwd" } })}
      />,
    );

    expect(titleText()).toBe('tool.shellCompleted[{"command":"ls"}]');
  });

  it("uses the default title when no intent or command was given", () => {
    render(<ShellCard content={createContent({ params: {} })} />);

    expect(titleText()).toBe("tool.shellCompletedDefault");
  });

  it("uses the default title when the call carries no params", () => {
    render(<ShellCard content={createContent({ params: NO_PARAMS })} />);

    expect(titleText()).toBe("tool.shellCompletedDefault");
  });

  it("shows the command output in the output block", () => {
    render(<ShellCard content={createContent()} />);

    expect(screen.getByTestId("block-Output").textContent).toBe("total 0");
  });

  it("renders no output block when the shell produced no text", () => {
    render(<ShellCard content={createContent({ result: "" })} />);

    expect(screen.queryByTestId("block-Output")).toBeNull();
    expect(screen.getByTestId("card-body").textContent).toBe("");
  });

  it("renders no output block when the call failed", () => {
    render(
      <ShellCard
        content={createContent({ status: "error", result: "boom" })}
      />,
    );

    expect(screen.queryByTestId("block-Output")).toBeNull();
    expect(screen.getByTestId("card-body").textContent).toBe("");
  });

  it("still shows the intent in the title of a failed call", () => {
    render(<ShellCard content={createContent({ status: "error" })} />);

    expect(titleText()).toBe(
      'tool.shell[{"command":"Inspect workspace files"}]',
    );
  });

  it("renders no output block when the result is not text", () => {
    render(<ShellCard content={createContent({ result: { code: 1 } })} />);

    expect(screen.queryByTestId("block-Output")).toBeNull();
  });

  it("does not expose a large command when an intent is available", () => {
    const command = `python -c ${"x".repeat(20_000)}`;

    render(
      <ShellCard
        content={createContent({
          params: { command, title: "Process generated data" },
        })}
      />,
    );

    expect(titleText()).toBe(
      'tool.shellCompleted[{"command":"Process generated data"}]',
    );
    expect(titleText()).not.toContain(command);
  });

  it("keeps long command endings distinguishable without an intent", () => {
    const commonPrefix = `curl ${"x".repeat(140)}`;
    const firstCommand = `${commonPrefix}/first-response.json`;
    const secondCommand = `${commonPrefix}/second-response.json`;
    const { rerender } = render(
      <ShellCard
        content={createContent({ params: { command: firstCommand } })}
      />,
    );
    const firstTitle = titleText();

    rerender(
      <ShellCard
        content={createContent({ params: { command: secondCommand } })}
      />,
    );
    const secondTitle = titleText();

    expect(firstTitle).toContain("…");
    expect(firstTitle).toContain("/first-response.json");
    expect(secondTitle).toContain("/second-response.json");
    expect(firstTitle).not.toBe(secondTitle);
  });

  it("updates the title after a long-running command ends", () => {
    const running = createContent({ status: "calling", result: "" });
    const { rerender } = render(<ShellCard content={running} />);

    expect(titleText()).toBe(
      'tool.shell[{"command":"Inspect workspace files"}]',
    );
    expect(screen.queryByTestId("block-Output")).toBeNull();

    rerender(<ShellCard content={createContent()} />);

    expect(titleText()).toBe(
      'tool.shellCompleted[{"command":"Inspect workspace files"}]',
    );
  });
});
