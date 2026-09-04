// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { IAgentScopeRuntimeResponse } from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/types";

vi.mock("../../utils/resolveBackendSessionId", () => ({
  resolveBackendSessionId: () => "session-active",
}));

import { ToolCallTurnBoundary } from "./turnEndedProvider";
import {
  clearTurnStopped,
  markTurnStopped,
  useStoppedTurnsStore,
} from "./stoppedTurns";
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

beforeEach(() => {
  useStoppedTurnsStore.setState({ stoppedSessionId: null });
});

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

  it("reports a stopped turn as ended although its status never changed", () => {
    // Stop issued after the stream died: the SDK never observes the abort, so
    // the response stays in progress and only the stop itself is left.
    markTurnStopped();

    renderBoundary("in_progress");

    expect(turnEnded()).toHaveTextContent("true");
  });

  it("ignores a stop recorded for another session", () => {
    useStoppedTurnsStore.setState({ stoppedSessionId: "session-other" });

    renderBoundary("in_progress");

    expect(turnEnded()).toHaveTextContent("false");
  });

  it("reports the next turn as running once the stop signal is cleared", () => {
    markTurnStopped();
    // Every new stream request clears the signal (customFetch / reconnect).
    clearTurnStopped();

    renderBoundary("in_progress");

    expect(turnEnded()).toHaveTextContent("false");
  });
});

describe("stoppedTurns", () => {
  it("records the active session on stop", () => {
    markTurnStopped();

    expect(useStoppedTurnsStore.getState().stoppedSessionId).toBe(
      "session-active",
    );
  });

  it("clears the signal", () => {
    markTurnStopped();
    clearTurnStopped();

    expect(useStoppedTurnsStore.getState().stoppedSessionId).toBeNull();
  });

  it("keeps the same state object when clearing an empty signal", () => {
    const before = useStoppedTurnsStore.getState();
    clearTurnStopped();

    expect(useStoppedTurnsStore.getState()).toBe(before);
  });
});
