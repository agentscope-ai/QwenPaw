// @vitest-environment jsdom
/**
 * Contract tests for ShellCard.
 *
 * Two behaviours are worth pinning. First the command text: shells accept the
 * command under two different param names, and a call that carries neither
 * still has to render with the generic title instead of an empty one. Second
 * the failed-call shape: when the shell errored the card deliberately renders
 * no output block at all, because the error surface belongs to the shell and
 * showing a stale stdout next to it would be misleading.
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
  params: { command: "ls -la" },
  result: "total 0",
  ...overrides,
});

const titleText = () => screen.getByTestId("card-title").textContent;

describe("ShellCard", () => {
  it("puts the command in the title", () => {
    render(<ShellCard content={createContent()} />);

    expect(titleText()).toBe('tool.shell[{"command":"ls -la"}]');
  });

  it("accepts the command under the cmd param name too", () => {
    render(<ShellCard content={createContent({ params: { cmd: "pwd" } })} />);

    expect(titleText()).toBe('tool.shell[{"command":"pwd"}]');
  });

  it("prefers command over cmd when both are present", () => {
    render(
      <ShellCard
        content={createContent({ params: { command: "ls", cmd: "pwd" } })}
      />,
    );

    expect(titleText()).toBe('tool.shell[{"command":"ls"}]');
  });

  it("uses the default title when no command was given", () => {
    render(<ShellCard content={createContent({ params: {} })} />);

    expect(titleText()).toBe("tool.shellDefault");
  });

  it("uses the default title when the call carries no params", () => {
    render(<ShellCard content={createContent({ params: NO_PARAMS })} />);

    expect(titleText()).toBe("tool.shellDefault");
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

  it("still names the command in the title of a failed call", () => {
    render(<ShellCard content={createContent({ status: "error" })} />);

    expect(titleText()).toBe('tool.shell[{"command":"ls -la"}]');
  });

  it("renders no output block when the result is not text", () => {
    render(<ShellCard content={createContent({ result: { code: 1 } })} />);

    expect(screen.queryByTestId("block-Output")).toBeNull();
  });

  it("titles a running shell the same way as a finished one", () => {
    render(
      <ShellCard content={createContent({ status: "calling", result: "" })} />,
    );

    expect(titleText()).toBe('tool.shell[{"command":"ls -la"}]');
    expect(screen.queryByTestId("block-Output")).toBeNull();
  });
});
