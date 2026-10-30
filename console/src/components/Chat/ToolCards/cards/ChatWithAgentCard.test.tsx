// @vitest-environment jsdom
/**
 * Contract tests for ChatWithAgentCard.
 *
 * The card names the agent it talked to. The interesting contract is the
 * fallback: an inter-agent call that carries no to_agent must still render a
 * readable title rather than an empty one, because the card is what the user
 * sees in the transcript while the call is still running.
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

import ChatWithAgentCard from "./ChatWithAgentCard";

const NO_PARAMS = undefined as unknown as Record<string, unknown>;

const createContent = (
  overrides: Partial<ToolCallContent> = {},
): ToolCallContent => ({
  type: "tool_call",
  id: "chat-agent-1",
  name: "chat_with_agent",
  status: "done",
  params: { to_agent: "qpqat-envoy" },
  result: "acknowledged",
  ...overrides,
});

const titleText = () => screen.getByTestId("card-title").textContent;

describe("ChatWithAgentCard", () => {
  it("names the target agent in the title", () => {
    render(<ChatWithAgentCard content={createContent()} />);

    expect(titleText()).toBe('tool.chatWithAgent[{"agent":"qpqat-envoy"}]');
  });

  it("uses the default title when no agent was given", () => {
    render(<ChatWithAgentCard content={createContent({ params: {} })} />);

    expect(titleText()).toBe("tool.chatWithAgentDefault");
  });

  it("uses the default title when the call carries no params", () => {
    render(
      <ChatWithAgentCard content={createContent({ params: NO_PARAMS })} />,
    );

    expect(titleText()).toBe("tool.chatWithAgentDefault");
  });

  it("shows the reply in the output block", () => {
    render(<ChatWithAgentCard content={createContent()} />);

    expect(screen.getByTestId("block-Output").textContent).toBe("acknowledged");
  });

  it("renders no output block when the agent sent nothing back", () => {
    render(<ChatWithAgentCard content={createContent({ result: "" })} />);

    expect(screen.queryByTestId("block-Output")).toBeNull();
    expect(screen.getByTestId("card-body").textContent).toBe("");
  });

  it("renders no output block when the reply is not text", () => {
    render(
      <ChatWithAgentCard content={createContent({ result: { ok: true } })} />,
    );

    expect(screen.queryByTestId("block-Output")).toBeNull();
  });

  it("keeps naming the agent while the call is still running", () => {
    render(
      <ChatWithAgentCard
        content={createContent({ status: "calling", result: "" })}
        isStreaming
      />,
    );

    expect(titleText()).toBe('tool.chatWithAgent[{"agent":"qpqat-envoy"}]');
    expect(screen.queryByTestId("block-Output")).toBeNull();
  });
});
