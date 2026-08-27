// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { IAgentScopeRuntimeResponse } from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/types";
import { ToolCallTurnBoundary } from "./turnEndedProvider";
import { useToolCallTurnEnded } from "../../components/Chat/ToolCards/shared/ToolCallTurnContext";

const Probe = () => (
  <span data-testid="turn-ended">{String(useToolCallTurnEnded())}</span>
);

const renderBoundary = (status: string) =>
  render(
    <ToolCallTurnBoundary
      data={{ status, output: [] } as unknown as IAgentScopeRuntimeResponse}
    >
      <Probe />
    </ToolCallTurnBoundary>,
  );

const turnEnded = () => screen.getByTestId("turn-ended");

describe("ToolCallTurnBoundary", () => {
  // A turn keeps streaming tool calls, results and further messages while it
  // is in progress; closing calls here would flag every healthy tool as
  // interrupted until its output arrives.
  it("reports a created turn as running", () => {
    renderBoundary("created");

    expect(turnEnded()).toHaveTextContent("false");
  });

  it("reports an in-progress turn as running", () => {
    renderBoundary("in_progress");

    expect(turnEnded()).toHaveTextContent("false");
  });

  it("reports a canceled turn as ended", () => {
    renderBoundary("canceled");

    expect(turnEnded()).toHaveTextContent("true");
  });

  it("reports a failed turn as ended", () => {
    renderBoundary("failed");

    expect(turnEnded()).toHaveTextContent("true");
  });

  it("reports restored history as ended", () => {
    // Session history is rebuilt with a completed status.
    renderBoundary("completed");

    expect(turnEnded()).toHaveTextContent("true");
  });
});
